---
name: vps-disk-doctor
description: >
  Finds out what is filling the disk of a Linux VPS that runs Docker (Coolify, Dokploy,
  plain compose) and says what can be reclaimed safely. Runs from your workstation over one
  SSH call, read-only by default: ranks the biggest paths, then classifies the usual
  culprits — Docker build cache, unused/dangling images, orphan volumes (mounted by no
  container), unbounded json-file container logs, local backup sets kept on the disk they
  back up, oversized journal/apt cache, deleted-but-still-open files, swapfiles, loose big
  files — each with a risk level (SAFE / REVIEW / NEVER) and the fix that stops it coming
  back. Removal is a separate armed command limited to a SAFE whitelist. Use when the
  hosting provider sends a "disk almost full" alert, when deploys start failing with
  "no space left on device", or as a periodic check.
---

# vps-disk-doctor agent

You answer, in order: **"what is eating the disk?"**, **"why does it keep coming back?"**
and **"what can go right now without risk?"** — on a production box, where a wrong `rm`
takes a paying customer offline.

The hands are [`vpsdisk.py`](vpsdisk.py) — **stdlib only**, Python 3.10+, runs on Windows,
macOS or Linux. It needs `ssh` on PATH and key access to the host. No config file, no secrets
stored: host and key come from `--host` / `-i` or `VPSDISK_HOST` / `VPSDISK_KEY`.

> **Unbreakable rule: `scan` is read-only.** Deletion lives only in `clean`, which accepts a
> fixed whitelist of SAFE actions, is a dry run unless `--armed`, and refuses unless
> `--confirm` equals the remote hostname. Anything REVIEW is done by a human, by hand.

## Commands

```bash
python vpsdisk.py --host root@<ip> -i ~/.ssh/<key> scan [--json out.json] [--markdown out.md]

python vpsdisk.py --host root@<ip> -i ~/.ssh/<key> clean --only builder,dangling          # dry run
python vpsdisk.py --host root@<ip> -i ~/.ssh/<key> clean --only builder,dangling \
       --armed --confirm <remote-hostname>                                               # executes
```

`clean` whitelist: `builder` (`docker builder prune -af`), `dangling` (`docker image prune -f`),
`journal` (`journalctl --vacuum-size=200M`), `apt` (`apt-get clean`). Every armed run prints
df before/after and appends a line to `/var/log/vps-disk-doctor.log` on the host.

## Risk matrix

| Category | Risk | Why |
|---|---|---|
| `build_cache` | SAFE | Only costs a slower next build. On a PaaS that builds on the box it is usually the #1 culprit. |
| `journal`, `apt_cache` | SAFE | Regenerable, capped by config. |
| `images_unused` | REVIEW | Dangling `<none>` are safe (`clean --only dangling`), but tagged unused images are the **rollback targets** of Coolify/Dokploy. `prune -a` kills rollback. |
| `orphan_volume` | REVIEW | Either legacy data (app moved to S3/R2) **or** a compose edit that dropped a mount — in which case the app is now writing live data *inside* the container and loses it on every redeploy. Find out which before anything else. |
| `local_backups` | REVIEW | Backups on the same disk protect nothing against losing the disk and double the usage while a run is staging. |
| `container_log`, `var_log`, `big_file`, `deleted_open` | REVIEW | Case by case. `deleted_open`: df counts it, du does not — restart the holder. |
| `swap` | NEVER | Sized on purpose; report it so nobody wonders where the GBs went. |

## Investigation playbook (what the report does not decide for you)

1. **Correlate the alert time with the cron list** the report prints. A provider alert at
   03:30 next to a `0 3 * * *` backup job means the peak is the backup staging, not steady state.
2. **Compare with the last cleanup's df** ("Past cleanup runs"). Fast regrowth between weekly
   prunes = build cache from frequent deploys → prune **daily** with an age filter, e.g.
   `docker builder prune -af --filter until=24h`. Note `docker builder prune -f` *without* `-a`
   only drops dangling cache and usually frees ~0 B.
3. **Orphan volumes**: check the app's current compose/env (object-storage vars like `R2_*`,
   `S3_*`, `STORAGE_TYPE`) and the newest file date in the volume. Legacy → archive off-box,
   drop from the backup job, then remove. Recent writes → it was un-mounted by mistake: fix the
   mount first, it is an incident.
4. **Backup tools** that write a full local set then upload: the peak is previous + current.
   Fix in the tool — delete the previous local set *before* staging, keep 0–1 local sets, or
   stream to the bucket.
5. **Coolify specifics**: its own server settings carry `docker_cleanup_threshold`
   (default 80%) and `docker_cleanup_frequency`; its DB dumps live in `/data/coolify/backups`
   and keep growing unless retention is set in the backup schedule. Resolved compose + env per
   app live in `/data/coolify/applications/<uuid>/`.
6. Always finish with a prevention item, not just a clean. A disk that is cleaned without
   changing the schedule fills again.

## Output

A markdown report (stdout, optional `--markdown`) with: usage headline + SAFE-reclaimable
total, top paths, `/var/lib/docker` breakdown, findings sorted by size with risk + fix,
scheduled jobs, and past cleanup history. `--json` gives the same data for automation.
