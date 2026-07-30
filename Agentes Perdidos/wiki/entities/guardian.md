---
title: guardian agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/guardian/SKILL.md, agents/guardian/DISASTER-RECOVERY.md, agents/guardian/config.example.json]
tags: [agent, backup, disaster-recovery, docker, vps, b2]
---

VPS **backup + disaster-recovery daemon**. Auto-discovers every meaningful docker volume on a host (app data + PaaS control-plane), tars each, keeps **one** local copy, and pushes to a **PRIVATE** Backblaze B2 bucket with rolling **3-daily + 3-weekly** retention per volume. Reports to WhatsApp. A companion restore tool rebuilds all volumes on a fresh machine from B2.

## What it backs up
`docker volume ls` minus `exclude_patterns` (default: anonymous 64-hex volumes + anything matching `redis` — caches are ephemeral). Everything else: app uploads, every postgres/pg volume, **and the PaaS control-plane** (`coolify-db`, `dokploy-postgres`) so a dead VPS can be rebuilt end-to-end.

## Retention
- **Local**: newest `local_keep` backup folders (default **1**) under `backup_dir`.
- **B2** per volume: `guardian/<host>/<volume>/daily/<YYYYMMDD>.tar.gz` (keep 3) and, on `weekly_weekday` (default Saturday), a `…/weekly/<YYYYMMDD>.tar.gz` (keep 3).

## How it's invoked (NOT uv — runs on the box)
Self-contained: needs only `python3 + boto3 + docker` on the VPS — no repo checkout, no [[uv]]. Deployed by `install_guardian.sh` (copies scripts, installs boto3, writes `/etc/guardian/config.json`, schedules cron). Then:
- `guardian-backup run` — the backup run (cron calls this); also `check | list | stats | test`.
- `guardian-restore list` / `guardian-restore <...>` — disaster recovery from B2 (runbook in `DISASTER-RECOVERY.md`).
- `config.example.json` is the shape of `/etc/guardian/config.json`.

## Env keys (names only — never values)
Shares the **PRIVATE** B2 bucket of the [[bucket]] agent: `B2_PRIVATE_KEY_ID`, `B2_PRIVATE_APPLICATION_KEY` (+ the other `B2_PRIVATE_*` bucket/region/endpoint vars → `backupPessoalrobsDEV`). The bucket is private by design — these are archival backups, never browser-served. Plus a WhatsApp reporting webhook target (configured in `/etc/guardian/config.json`, not this repo's `.env`).

## Division of labor with navigator
None — guardian is an infra daemon that runs *on the server*, not a browser agent. It complements [[navigator]]'s deploy-panel work (navigator configures Coolify/Dokploy; guardian backs up their control-plane volumes). Per [[lost-agent-rule]], operational state lives on the host / in the target's brain, never here. See [[agentes-perdidos]] · [[bucket]].
