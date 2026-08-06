# Guardian — Disaster Recovery runbook

Goal: a VPS died. Rebuild it (or move to a new one) from the PRIVATE B2 backups.

## 0. Prereqs on the new machine
- Docker installed and running.
- `python3 + boto3` and the guardian scripts (`bash install_guardian.sh` installs both, or copy
  `restore_guardian.py` → `/usr/local/bin/guardian-restore` and `pip3 install boto3`).
- `/etc/guardian/config.json` with the B2 creds + the dead host's `host_label`.

## 1. See what's recoverable
```bash
guardian-restore list                 # all hosts, volumes, daily/weekly dates
guardian-restore show --host coolify  # latest manifest (key per volume)
```

## 2. Recreate the docker volumes
Restore **before** the PaaS recreates apps, so containers mount populated volumes.
```bash
guardian-restore restore --host coolify --all            # newest of each
# or a point in time:
guardian-restore restore --host coolify --all --when weekly:20260621 --force
```
`--force` wipes+overwrites an existing volume; omit it to skip volumes that already exist.

## 3. Bring the PaaS back

### Coolify (host_label `coolify`)
1. Install Coolify normally (it creates `coolify-db` / `coolify-redis`).
2. Stop Coolify, **restore `coolify-db`** over the fresh one:
   `guardian-restore restore --host coolify --volume coolify-db --force`
3. Start Coolify → it reads the restored control-plane DB: all apps, env vars, deploy config return.
4. Redeploy each app. Their `*_postgres-data` / `*_app-uploads` volumes are already populated, so
   data comes back with them.

### Dokploy (host_label `oracle`)
1. Install Dokploy (creates `dokploy-postgres` / `dokploy-redis` / `dokploy`).
2. Stop Dokploy stack, **restore `dokploy-postgres`** (and `dokploy`):
   `guardian-restore restore --host oracle --volume dokploy-postgres dokploy --force`
3. Start Dokploy → projects/compose/env return. Redeploy; data volumes are already restored.

## 4. Verify
```bash
guardian-backup check     # docker + B2 OK
docker volume ls          # restored volumes present
```
Then trigger one backup to confirm the cycle: `guardian-backup run`.

## Notes
- Redis is intentionally NOT backed up (cache). Apps rebuild it.
- Postgres volumes are filesystem snapshots; on rare corruption, prefer the previous daily/weekly
  (`--when daily:YYYYMMDD`).
- Keys are namespaced `guardian/<host>/…` so one bucket safely holds every VPS.
