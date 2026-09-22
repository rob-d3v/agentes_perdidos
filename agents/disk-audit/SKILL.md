---
name: disk-audit
description: >
  Finds out what is actually eating a Windows disk and says what can be deleted safely.
  Walks one or more drives with a junction-aware, long-path-aware scanner, ranks the biggest
  directories, and classifies every finding into recoverable-junk categories (node_modules,
  build output, Python caches, bloated .git, package-manager caches under AppData, WSL/Docker
  .vhdx, Windows temp/update junk, huge loose files, exact duplicates) with a risk level:
  SAFE (regenerable — delete freely), REVIEW (probably junk — confirm), NEVER (system/user
  data — reported for size only, structurally undeletable). Reports by default and NEVER
  deletes on its own; removal is a separate armed command that only accepts SAFE findings
  from a report you already read, prints the exact plan, demands a typed confirmation, and
  logs every removal. Use when a drive is fuller than it should be, before buying storage,
  or to clean up a dev machine with dozens of repos.
---

# disk-audit agent

You answer two questions about a full disk, in this order: **"where did the space go?"** and
**"what can I delete without breaking anything?"** — and you answer the second one with a risk
level attached, because on a dev machine the difference between `node_modules` and `.git` is
the difference between a 30-second `npm i` and a lost repository.

The hands are [`diskaudit.py`](diskaudit.py) — **stdlib only**, no `uv` deps, runs with plain
`python` (3.10+) from PowerShell or Git Bash. There is no config file and no `.env`; this
agent needs no credentials.

> **The one unbreakable rule: `scan` is read-only.** Every reporting subcommand is incapable
> of removing anything. Deletion lives in exactly one place — `clean` — and it will not run
> without an armed flag *and* a typed confirmation *and* a SAFE-only target list that it
> re-verifies itself. If you are unsure, you report. You never delete to "help".

## Risk matrix — the core of the agent

| Risk | Meaning | May `clean` remove it? |
|---|---|---|
| **SAFE** | Regenerable by a single documented command. Losing it costs time, never data. | **yes** |
| **REVIEW** | Almost certainly junk, but the rebuild may be slow, offline-impossible, or the dir name is ambiguous. | **no** — surface it, let the human decide |
| **NEVER** | Windows-managed or user data. Reported for size + how to shrink it properly. | **no**, structurally |

`clean` accepts only these categories — the list is a constant in the script, not a heuristic:
`node_modules`, `python_cache`, `build_cache`, `pkg_cache`, `android_build`.

## What it classifies

| Category | Matches | Risk | How to reclaim |
|---|---|---|---|
| `node_modules` | `node_modules/` | SAFE | `npm i` / `pnpm i` |
| `python_cache` | `__pycache__` `.pytest_cache` `.mypy_cache` `.ruff_cache` `.tox` `.cache` | SAFE | rebuilt on demand |
| `build_cache` | `.next` `.nuxt` `.turbo` `.parcel-cache` `.svelte-kit` `.angular` `.dart_tool` `.expo` `.vite` `coverage` `.gradle` | SAFE | next build recreates it |
| `build_output` | `dist` `build` `out` `webbuild` `release` `target` — **only if the parent looks like a repo** | REVIEW | delete after proving a rebuild works |
| `dotnet_output` | `bin` `obj` — **only next to a `.csproj`/`.sln`** | REVIEW | `dotnet build` |
| `python_env` | `.venv` `venv` `env` — **only if it contains `pyvenv.cfg`** | REVIEW | `uv sync` / `pip install -r …` (needs network) |
| `git_bloat` | a `.git` disproportionate to its working tree (>2× and >50 MB, or >200 MB) | REVIEW | `git gc --aggressive --prune=now` — **never delete `.git`** |
| `pkg_cache` | npm/pnpm/yarn/pip/uv/cargo/gradle/maven/nuget/go caches under `AppData` & `~` | SAFE | the package manager's own `cache clean` |
| `temp_dir` / `ide_cache` | `%TEMP%`, `LocalAppData\JetBrains` | REVIEW | Storage Sense; per-IDE cache dirs only |
| `docker_wsl` | `*.vhdx` of WSL distros / Docker Desktop | REVIEW | **compact, never delete** (see below) |
| `windows_junk` | `Windows\Temp`, `SoftwareDistribution\Download`, `Windows.old`, `$WinREAgent`, WER, Delivery Optimization, minidumps | REVIEW | Disk Cleanup / the documented service dance |
| `large_files` | loose files ≥ `--large-file` (default 500 MB): APK, ISO, tar.gz, `.bak`, DB dumps | REVIEW | triage one by one |
| `duplicates` | byte-identical files (same size **and** same sha256) | REVIEW | keep one copy |
| `system_files` | `pagefile.sys` `hiberfil.sys` `swapfile.sys`, `WinSxS`, `Windows\Installer`, `Prefetch`, System Volume Information | **NEVER** | reported with the *correct* way to shrink |

The guards in the "only if" column matter: `build`, `out`, `target` and `bin` are extremely
common names for **source** directories. Without a repo marker in the parent they are not
flagged at all.

## Commands

```bash
# the audit (read-only). E: is the repo drive; depth 3 is the sweet spot.
python diskaudit.py scan E:\ --depth 3 --dupes \
    --json E:\disk-audit-E.json --markdown E:\disk-audit-E.md

# the system drive: add --vhdx (automatic when the root covers the user profile)
python diskaudit.py scan C:\ --depth 3 --json C:\disk-audit-C.json

# fast, targeted probes — seconds, not minutes, no full walk
python diskaudit.py caches                 # every package-manager cache + its clean command
python diskaudit.py windows                # Windows junk, WSL/Docker vhdx, pagefile/hiberfil
python diskaudit.py repos E:\path\to\repo-forest   # .git bloat ranking across N repos
python diskaudit.py dupes E:\ --dupe-min 10MB      # duplicates only

# verify the risky machinery (ctypes struct, path guards). Deletes nothing.
python diskaudit.py selftest

# removal — read the report FIRST, then arm it
python diskaudit.py clean --from E:\disk-audit-E.json --category node_modules --dry-run
python diskaudit.py clean --from E:\disk-audit-E.json --category node_modules \
    --yes-delete-for-real          # then type DELETE at the prompt
```

Useful flags on `scan`: `--depth N` (ranking depth), `--top N`, `--min-size 100MB`,
`--large-file 500MB`, `--on-disk` (round every file up to the cluster — the *real* size on
disk, which matters a lot for `node_modules`), `--exclude GLOB` (repeatable), `--no-git`,
`--json-only`, `--quiet`.

## Workflow (do it in this order)

1. **Scan read-only, always to `--json`.** Never start with `clean`. The JSON is the contract:
   `clean` refuses any path that is not in a report it can re-verify.
2. **Read the category table first, not the path list.** The answer is almost always one or
   two categories, not a hundred directories.
3. **Report to the human in three buckets**: SAFE total (what a single command frees), REVIEW
   total (what needs a decision), NEVER total (what they must stop hoping to delete). Give the
   *command* for each, not just the size.
4. **Clean the SAFE tier first**, one category at a time, `--dry-run` before the real run. Free
   the biggest category first and re-measure — often that alone ends the problem.
5. **Then work the REVIEW tier interactively**, biggest first, asking per item. `git gc` the
   bloated repos (never `rm -rf .git`). Compact the vhdx files. Point Windows junk at Disk
   Cleanup / Storage Sense rather than deleting it yourself.
6. **Record the result in the target machine's brain** — write the `--markdown` output into the
   user's second-brain (it already ships the right YAML frontmatter) so the next audit has a
   baseline to diff against.

## Gotchas

- **Junctions and symlinks are never followed.** This is not an optimization, it is correctness:
  `C:\Users\<u>\AppData\Local\Application Data` is a junction to its own parent, so a naive
  walker loops forever and double-counts everything under `AppData`. The scanner tests
  `FILE_ATTRIBUTE_REPARSE_POINT` on every entry and skips it, counting **0 bytes** for the link
  (the target is counted once, where it really lives). The report prints how many were skipped.
- **Long paths.** Every path is opened through the `\\?\` prefix, so a 470-character
  `node_modules` tree is sized instead of raising. But **`SHFileOperationW` — the Recycle Bin
  API — does not understand that prefix and is MAX_PATH-bound**, so recycling a deep tree can
  fail with `0x7C`. That is a refusal, not a partial delete; retry with `--permanent`.
- **The Recycle Bin is not a safety net for big items.** `clean` recycles by default, but
  Windows deletes an item **permanently and silently** when it exceeds the bin quota, and we
  pass `FOF_NOCONFIRMATION`. A 3 GB `node_modules` will very likely be gone for good. The
  command prints this warning every single time; do not suppress it, and never tell the user
  "it's in the Recycle Bin, you can undo it" without checking.
- **`--on-disk` vs logical size.** Default is logical (`st_size`). `--on-disk` rounds each file
  up to the volume's cluster size — much closer to what Explorer's "Size on disk" shows for
  trees of tiny files, but it does not model NTFS compression, sparse files or MFT-resident
  files. Do not present it as exact.
- **WSL / Docker `.vhdx` files only grow.** Deleting one destroys the distro or every container
  volume inside it — this agent classifies them REVIEW and never offers to remove them. The
  real fix is `wsl --shutdown` then `wsl --manage <distro> --set-sparse true`, or
  `Optimize-VHD`, or `diskpart` → `select vdisk file="…"` → `attach vdisk readonly` →
  `compact vdisk` → `detach vdisk`. `docker system prune -a --volumes` first, or you compact
  nothing.
- **`pagefile.sys` / `hiberfil.sys` are never deletable here** — they are reported with the
  correct fix (`powercfg /h off`; System Properties → Performance → Virtual memory). Deleting
  them by hand is how people break boot.
- **`.git` is a protected basename.** Even if the user asks, `clean` refuses any path named
  `.git`, any path containing a `.git` child, anything under `%SystemRoot%` / `Program Files` /
  the profile's Documents-Desktop-Downloads-Pictures set, anything crossing a `$`-prefixed
  system dir, and anything less than two levels below a volume root.
- **Duplicates are hashed lazily.** Files are grouped by exact size first, then a 64 KiB head
  hash, then a full streamed sha256 — hashing a whole drive up front would take hours. Default
  floor is 1 MiB; raise it with `--dupe-min` on a big drive.
- **Permission denied / file in use is never fatal.** Unreadable paths are counted and listed at
  the end of the report. Running an audit of `C:\` from a non-elevated shell is fine and
  expected — some `ProgramData` and `System Volume Information` subtrees will simply be missing
  from the total, and the report says so.
- **Cold cache dominates the first run.** A first `scan` of a large drive is I/O bound (minutes);
  an immediate re-scan of the same tree is seconds. Do not benchmark the second run.
