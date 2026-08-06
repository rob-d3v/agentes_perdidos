---
name: guardian
description: >
  VPS backup + disaster-recovery daemon. Auto-discovers every meaningful docker volume on a
  host (app data + PaaS control-plane), tars each, keeps ONE local copy, and pushes to a PRIVATE
  Backblaze B2 bucket with rolling 3-daily + 3-weekly retention per volume. Reports to WhatsApp.
  Companion restore tool rebuilds all volumes on a fresh machine from B2. Use to set up / operate
  automated container backups across VPSs (Coolify, Dokploy, plain docker) or to recover one.
---

# guardian agent

Cron-driven backup for any docker VPS, plus one-command disaster recovery. Self-contained:
needs only `python3 + boto3 + docker` on the box — no repo checkout, no `uv`.

Shares the **PRIVATE** B2 bucket of the `bucket` agent (`B2_PRIVATE_*` → `backupPessoalrobsDEV`).
The bucket is private by design; these are archival backups, never browser-served.

## Files

| File | Role |
|------|------|
| `backup_guardian.py` | the backup run (cron calls `guardian-backup run`) |
| `restore_guardian.py` | disaster recovery (`guardian-restore …`) |
| `install_guardian.sh` | deploy to a VPS: copies scripts, installs boto3, writes config, schedules cron |
| `config.example.json` | shape of `/etc/guardian/config.json` |
| `DISASTER-RECOVERY.md` | runbook to rebuild a dead VPS from B2 |

## What it backs up

`docker volume ls` minus `exclude_patterns` (default: anonymous 64-hex volumes + anything
matching `redis` — caches are ephemeral). Everything else is captured: app uploads, every
postgres/pg volume, **and the PaaS control-plane** (`coolify-db`, `dokploy-postgres`) so a VPS
can be rebuilt end-to-end.

## Retention

- **Local**: newest `local_keep` backup folders (default **1**) under `backup_dir`.
- **B2** per volume: `guardian/<host>/<volume>/daily/<YYYYMMDD>.tar.gz` (keep 3) and, on
  `weekly_weekday` (default Saturday), a copy under `…/weekly/<YYYYMMDD>.tar.gz` (keep 3).
- A `guardian/<host>/LATEST.json` manifest records the current key per volume — restore reads it.

## Operate

```bash
guardian-backup check     # docker + B2 reachable?
guardian-backup list      # which volumes WOULD be backed up
guardian-backup run       # do a backup now (what cron runs)
guardian-backup test      # WhatsApp test ping
guardian-backup stats     # local + B2 inventory

guardian-restore list                          # hosts/volumes/dates in B2
guardian-restore restore --host coolify --all  # rebuild every volume from latest
guardian-restore restore --host coolify --volume foo_pg-data --when weekly:20260621 --force
```

## Install on a VPS

```bash
GUARDIAN_HOST_LABEL=coolify \
B2_KEY_ID=… B2_APPLICATION_KEY=… B2_BUCKET=backupPessoalrobsDEV B2_REGION=us-east-005 \
WA_API_URL=https://evo.obra.vision WA_INSTANCE=diario_obras_instance WA_API_KEY=… WA_NUMBER=55… \
bash install_guardian.sh
```

Each VPS needs a **unique** `GUARDIAN_HOST_LABEL` (keys are namespaced by it in the shared bucket).

## Gotchas

- Postgres volumes are tarred live (crash-consistent snapshot). Fine for restore in practice; for a
  guaranteed-clean dump, add a `pg_dump` pre-step per app.
- Dokploy volume names carry a random `compose-<rand>_` prefix that changes on redeploy → the B2
  key path changes and the old one ages out. Restore always uses the current `LATEST.json`.
- `--force` on restore **wipes** the target volume before extracting. Without it, existing volumes
  are skipped.
- See [[b2-private-bucket]] for creds; pairs with the `bucket` agent.
