---
title: Hardening reversibility doctrine (3-layer reversible change)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, hardening, reversibility, doctrine, shared]
---

# Hardening reversibility doctrine (3-layer reversible change)

Any infra hardening change must be **reversible by construction** through three layers, because the
failure mode of hardening is locking yourself out of the box you were trying to protect. Every
touched file gets backed up, every change gets a rollback path, and lockout-class changes get an
automatic dead-man revert. Pairs with [[vps-hardening-playbook]].

## Layer 0 — snapshot gate (refuse if it fails)
Before any high-risk change, take a recoverable snapshot (cloud volume/VM snapshot, or a verified
[[vps-hardening-playbook|off-host backup]]). If the snapshot **cannot be confirmed**, the agent
**REFUSES** the high-risk change — no snapshot, no risky edit. This is the outermost safety net.

## Layer 1 — per-run backup dir + generated rollback.sh
Each run writes a **timestamped backup dir** (e.g. `/var/backups/hardening/<ts>/`) holding a copy of
every file it will touch (`sshd_config`, `daemon.json`, sysctl drop-ins, ufw rules). It then
**auto-generates a `rollback.sh`** that restores each file from that dir **and reloads the relevant
service** (`sshd -t && systemctl reload ssh`, `ufw reload`, `sysctl --system`). One script returns
the host to its pre-run state.

## Layer 2 — time-boxed watchdog for lockout-class changes
For changes that can **lock you out** — SSH config, firewall rules — schedule a **dead-man revert**:
`at`/systemd-timer that runs `rollback.sh` in N minutes **unless** a confirmation file is touched
after you verify a fresh session still works. Apply the change, prove a new login succeeds, then
cancel the watchdog. If you locked yourself out, it auto-reverts.

## Risk classification (drives autonomy)
- **LOW-risk → auto-apply after snapshot.** Idempotent, non-lockout, easily reverted: enabling
  unattended-(security)-upgrades, adding an auditd rule, installing fail2ban.
- **HIGH-risk → propose + ask.** Anything touching reachability/auth: SSH hardening, firewall
  policy, kernel networking sysctls, [[docker-bypasses-ufw|Docker/UFW]] interaction. Show the diff,
  the rollback, and the watchdog plan; get a human yes.

Never make a high-risk change that you don't already have a generated, tested way to undo.

Related: [[vps-hardening-playbook]] · [[docker-bypasses-ufw]] · [[rfc-3227-ir-state-machine]] · [[secret-remediation-reversibility]]
