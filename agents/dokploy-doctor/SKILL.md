---
name: dokploy-doctor
description: >
  Full read-only health check of a Dokploy / Docker Swarm Linux VPS (ARM64 or x86), over one
  SSH session from your workstation. Covers load, RAM/swap and PSI pressure, OOM kills, swarm
  services and failed tasks, containers restarting / unhealthy / OOM-killed / exited, per-container
  memory, Dokploy's own footprint (/etc/dokploy, deploy logs), Traefik certificate expiry and ACME
  errors, systemd timers and failed units, cron jobs installed on a box with no cron daemon, stale
  backup directories, journald limits, pending reboot — plus Oracle Cloud Always Free risks (idle
  reclamation thresholds on A1, the 200 GB boot+block storage budget). The disk part reuses
  vps-disk-doctor's probe and classifier. Reports only; the one removal command accepts only
  vps-disk-doctor's SAFE whitelist, is a dry run by default and needs --confirm <remote hostname>.
  Use when a Dokploy host feels slow, fills up, drops a service, or before adding a new app to it.
---

# dokploy-doctor agent

You answer **"is this Dokploy box healthy, and what will hurt next?"** — ranked by severity, with
the exact command to look closer or to fix, and without touching anything.

The hands are [`dokdoctor.py`](dokdoctor.py) — **stdlib only**, plain `python` 3.10+, runs on
your workstation (Windows, macOS, Linux). Host and key come from CLI args or env vars
(`DOKDOC_HOST`, `DOKDOC_KEY`, falling back to `VPSDISK_HOST`, `VPSDISK_KEY`). No config file,
no credentials stored.

> **The one unbreakable rule: `report` is read-only.** Everything it runs is a read: `/proc`,
> `docker ps/inspect/info/stats/logs`, `docker service ls/ps/inspect`, `systemctl show/list-*`,
> `journalctl` reads, `du`/`find`, and a parse of Traefik's `acme.json` that prints **only domain +
> expiry, never keys**. Removal lives in `clean` alone — and restarts, redeploys, prunes of images
> with tags, volume removal and log truncation are **not** in it at all: those are decisions for a
> human, reported with the command to run.

## Depends on vps-disk-doctor

The disk section is not a copy: `dokdoctor.py` imports `../vps-disk-doctor/vpsdisk.py` with
`importlib` and runs its `PROBE` + `analyse()` inside the same SSH session. Keep the two folders
side by side. Improve disk detection **there**, and both agents get it.

## Commands

```bash
# the health report (read-only, ONE ssh session, ~30 s to a few minutes on a big /var/lib/docker)
python dokdoctor.py --host ubuntu@<ip> -i ~/.ssh/<key> report \
    --json health.json --markdown health.md

# an ssh alias from ~/.ssh/config works too (user unknown -> sudo is used)
python dokdoctor.py --host my-dokploy-box report

# removal: SAFE-only whitelist shared with vps-disk-doctor (builder, dangling, journal, apt)
python dokdoctor.py --host ubuntu@<ip> -i <key> clean --only builder,dangling          # dry run
python dokdoctor.py --host ubuntu@<ip> -i <key> clean --only builder,dangling \
    --armed --confirm <remote hostname>
```

`--sudo auto|always|never` (default `auto`): Ubuntu cloud images log in as `ubuntu`/`opc`, which
usually cannot talk to docker, so the whole probe runs under `sudo -n bash -s` unless the SSH user
is `root`. Without passwordless sudo the tool stops with a clear message instead of producing a
report full of blanks.

## Severity

| Sev | Examples |
|---|---|
| **CRIT** | a swarm service at 0/N, a container in a restart loop, a cert expiring in < 7 days, a filesystem ≥ 90 %, RAM available < 5 %, docker unreachable |
| **HIGH** | failed/rejected swarm tasks (≥ 3), unhealthy / OOM-killed containers, OOM-killer events, failed systemd units or timers, **cron jobs on a box with no cron daemon**, a backup dir whose newest file is > 3 days old, cert < 25 days (renewal is failing), Always Free idle-reclamation metrics all under 20 %, disks over the 200 GB budget |
| **MEDIUM** | SAFE disk reclaim (build cache, dangling images, journal), exited non-swarm containers, Traefik ACME errors, big orphan volumes, disks at the whole free budget |
| **LOW / INFO** | journald without `SystemMaxUse`, pending reboot, old Dokploy deploy logs, swarm task history, swap |

Disk findings keep vps-disk-doctor's risk tag (`[SAFE]`, `[REVIEW]`, `[NEVER]`) inside the text.

## Workflow

1. **Run `report` to `--json` + `--markdown`.** Read the Findings table top-down; stop at the
   first CRIT and deal with it before anything else.
2. **Separate "safe to clean" from "needs a decision".** Only `[SAFE]` disk items go to `clean`,
   dry run first. Orphan volumes, tagged unused images, files in home dirs, local backup copies:
   report them with size + last-write date and ask the owner.
3. **Preventive fixes over cleanups**: a daily `docker builder prune -af --filter until=24h`
   timer, `SystemMaxUse=` for journald, `max-size` log-opts in `daemon.json`, moving cron jobs to
   systemd timers, excluding dead volumes from the nightly backup.
4. **Record the report in the machine's brain** so the next run has a baseline to diff against.

## Dokploy gotchas this agent looks for

- **Swarm hides restarts.** A crashing swarm service does not bump `RestartCount`; it spawns new
  tasks. The signal is `docker service ps` history (`Failed`/`Rejected` + `.Error`), which the
  report counts per service. Plain compose apps deployed by Dokploy are *not* swarm services —
  for those, `RestartCount`, `State.Health` and `OOMKilled` are the signal.
- **Deploy logs are never pruned** under `/etc/dokploy/logs`; the compose clones under
  `/etc/dokploy/compose/<app>/code` are regenerated on redeploy (never hand-edit them).
- **Dokploy volume names carry a random `compose-<rand>_` prefix** that changes when an app is
  recreated: the old volume becomes an orphan that nobody mounts but a volume-level backup keeps
  copying every night. Orphans show up in the disk section with size and last-write date.
- **"Cannot retrieve the ACME challenge"** in Traefik's log is a validation for a token this
  Traefik never issued: some *other* server is requesting a cert for a name whose DNS points here.
  Harmless until this host's own renewal (30 days before expiry) needs the same name.
- **No cron daemon.** Minimal images (and some hardened hosts) ship `/etc/cron.d` files with no
  `cron` service: the jobs are installed and never run. The report flags it, and the backup-dir
  freshness check usually shows the consequence.

## Oracle Cloud Always Free

Detected through the instance metadata endpoint (`169.254.169.254/opc/v2`); on other clouds the
section is simply absent.

- **Idle reclamation**: an Always Free instance can be reclaimed when, over 7 days, CPU p95 < 20 %
  **and** network < 20 % **and** (A1 shapes only) memory < 20 %. The report takes a 5-second CPU +
  network sample and the current memory use — a hint, not the 7-day p95; confirm in the OCI
  Console metrics. Converting the tenancy to Pay-As-You-Go removes idle reclamation while Always
  Free resources stay free.
- **Storage budget**: 200 GB of boot + block volumes for the **whole tenancy**. The report sums
  the attached disks (GiB). A box that already uses the full budget cannot grow its disk for free;
  cleanup is the only lever.
- **Arch**: A1 is `aarch64` — every image needs an arm64 build (`docker buildx imagetools inspect`).
