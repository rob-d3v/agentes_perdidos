---
name: bucket
description: >
  Offloads a project's static, browser-served assets (images, gifs, video, fonts, etc.)
  to object storage — Cloudflare R2 and/or Backblaze B2 — then rewrites the code to point
  at the public bucket URLs. Frees the VPS from serving heavy files and speeds up page loads
  via CDN. Scans the whole project, routes each asset to the best bucket for its purpose,
  uploads, verifies the public URL, and swaps the path in the source so everything keeps
  working. Use when a user wants to move assets to a bucket/CDN, cut VPS bandwidth, or speed
  up asset delivery.
---

# bucket agent

You move a project's heavy static assets off the app server and onto object storage, then
rewire the code to load them from the public bucket URL. Pages get faster (CDN), the VPS
stops shipping megabytes per visitor. **Nothing breaks** — every rewrite is exact and
reversible (`.bak` files), and you verify the public URL responds before trusting it.

The hands are [`bucketsync.py`](bucketsync.py) (run with `uv`). Credentials live in the repo
`.env` (`B2_*`, `R2_*`); never commit them.

## Two buckets, routed by purpose

| | Cloudflare R2 | Backblaze B2 |
|---|---|---|
| Egress | **free** + global CDN | cheap storage, paid egress (free via CF alliance) |
| Best for | **hot, browser-served** assets: images, gifs, fonts, small media | **large / video / archival / backend** blobs, backups |

`--provider auto` (default) sends hot small browser assets to **R2** and large (>25 MB) /
video / docs to **B2**. Falls back to whichever provider is configured. Force with
`--provider r2|b2`.

> ⚠️ The bucket must be **public-read** to serve files in a browser. A fresh B2/R2 bucket is
> private by default — make it public (B2: bucket settings → Public; R2: enable the public
> `r2.dev` domain or a custom domain) and set `*_PUBLIC_BASE_URL` in `.env`, or rewritten
> URLs will 403.

## What it scans

Walks the whole project (skips `node_modules`, `dist`, `.git`, `build`, `target`, etc.) and
finds every asset: `png jpg jpeg webp svg gif avif ico` · `mp4 webm mov` · `mp3 ogg wav` ·
`woff woff2 ttf otf` · `pdf`. For each, it finds where it's referenced in source and classifies:

- **browser-served** (a URL-string ref like `src="/images/x.png"`, `url(/img/x.gif)`, a
  string `"/assets/x.webp"`) → safe to upload + rewrite.
- **bundler-import** (`import x from './x.png'`, `import.meta.glob`) → **flagged, NOT
  auto-rewritten** (replacing the import path with a URL would break the build; handle those
  by hand or with a loader).
- **orphan** (on disk, never referenced) → reported, skipped unless `--include-orphans`.

## Commands

```bash
# 1. see what's there (no changes) — writes a manifest if --map given
uv run agents/bucket/bucketsync.py scan <project> --map manifest.json

# 2. connectivity / resolve bucket name
uv run agents/bucket/bucketsync.py buckets --provider b2

# 3. dry-run the upload + see the URL mapping it would produce
uv run agents/bucket/bucketsync.py upload <project> --provider auto --dry-run --map map.json

# 4. real upload (idempotent: skips keys that already exist)
uv run agents/bucket/bucketsync.py upload <project> --provider auto --map map.json

# 5. rewrite source paths -> public URLs (makes .bak backups; --dry-run to preview)
uv run agents/bucket/bucketsync.py rewrite <project> --map map.json --dry-run
uv run agents/bucket/bucketsync.py rewrite <project> --map map.json

# 6. confirm every public URL responds
uv run agents/bucket/bucketsync.py verify --map map.json

# all-in-one (asks for --yes before mutating)
uv run agents/bucket/bucketsync.py sync <project> --yes
```

Object keys include a short content hash (`<project>/<category>/<hash>-<name>.ext`) so a
changed file gets a new URL (cache-bust) and re-uploads are deduped. Uploads set a long
`Cache-Control: immutable` and the correct `Content-Type`.

## Workflow (do it safely)

1. **Scan** the project, read the report: how many browser-served assets, total weight, and
   which are bundler-imports (out of scope for auto-rewrite).
2. **Check buckets** are reachable and **public**; confirm `*_PUBLIC_BASE_URL`. If a bucket is
   private, tell the user to make it public first.
3. **Dry-run upload** to preview routing (which file → which bucket → which key/URL).
4. **Upload** for real. Then **rewrite --dry-run** to preview source diffs, then rewrite.
5. **Verify** all URLs return 200. Run the app/build to confirm assets still load.
6. Report: assets moved, bytes offloaded, files rewritten, any imports left for manual handling.

## Gotchas

- **Public bucket required** — private buckets 403 in the browser. Native B2 public URL form:
  `https://f<NNN>.backblazeb2.com/file/<bucket>/<key>`; or use the S3 path-style endpoint with a
  public bucket; or a custom domain. R2: `https://<id>.r2.dev/<key>` or a custom domain.
- **Bundler imports are skipped** by design. Frameworks (Vite/Next/CRA) fingerprint imported
  assets at build time; those already get hashed URLs. This agent targets runtime URL strings
  (the `public/` dir pattern), which is where VPS bandwidth actually goes.
- **Rewrites are reversible** via `.bak` files. Commit before a big rewrite anyway.
- **Backend assets**: if the backend serves/stores files (uploads, generated media), point it
  at the bucket too — same `B2_*`/`R2_*` creds via the S3 API. (This tool focuses on the
  frontend static set; backend wiring is app-specific.)
- Credentials are read from the repo `.env` (walked up from the script). Keep it gitignored.
