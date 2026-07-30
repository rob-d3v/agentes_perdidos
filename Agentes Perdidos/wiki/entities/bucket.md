---
title: bucket agent
type: entity
created: 2026-06-14
updated: 2026-06-14
sources: [agents/bucket/SKILL.md]
tags: [agent, bucket, cdn, storage]
---

Offloads a project's static, browser-served assets (images, gifs, video, fonts) to **object storage**, then rewrites the code to point at the public bucket URLs. Frees the VPS from serving heavy files and speeds page loads via CDN. Every rewrite is exact and **reversible** (`.bak` files), and the public URL is verified before being trusted.

## Two buckets, routed by purpose
| | Cloudflare R2 | Backblaze B2 |
|---|---|---|
| Egress | free + global CDN | cheap storage, paid egress (free via CF alliance) |
| Best for | hot, browser-served assets (images, gifs, fonts, small media) | large / video / archival / backend blobs, backups |

`--provider auto` (default) → hot small assets to R2, large (>25 MB) / video / docs to B2. Force with `--provider r2|b2`.

> ⚠️ The bucket must be **public-read** or rewritten URLs 403. Set `*_PUBLIC_BASE_URL` in `.env`.

## Key files
- `agents/bucket/SKILL.md` — brain + routing table.
- `agents/bucket/bucketsync.py` — the hands (run via [[uv]]).
- Keys: `B2_*`, `R2_*` (in repo `.env`).

Used by [[remodeling]] to publish assets. See [[agentes-perdidos]].
