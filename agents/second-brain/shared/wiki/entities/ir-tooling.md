---
title: Incident-response tooling
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, incident-response, forensics, tooling, shared]
---

# Incident-response tooling

The concrete tools that execute the [[rfc-3227-ir-state-machine]] — each entry says **what** it does
and **when** it runs in the volatility order. Volatile-capture tools run first; rootkit scanners run
last because rootkits lie to live tools.

## Triage collection
- **UAC** (`tclahr/uac`) — agentless live-response collector. Run the `ir_triage` profile, `-H` to
  hash collected artifacts, and **stream the output off-host** (`scp`/S3 destination) so you don't
  write evidence to the compromised disk. *When:* phases 3–6, the broad sweep.

## Memory (phase 2 — most volatile)
- **AVML** — Microsoft's static-binary Linux memory acquirer; no kernel headers/build needed, works
  across kernels. `./avml mem.lime`. *When:* phase 2, before anything touches process state.
- **LiME** — loadable-kernel-module memory dump; needs a matching build but captures full physical
  RAM. Alternative to AVML when you can build for the kernel.

## /proc live forensics (phase 3, read-only)
Inspect `/proc/<pid>/` for tells: `exe` symlink ending `(deleted)` (binary unlinked but running),
`cwd` in `/tmp` or `/dev/shm`, and **`comm` ≠ `cmdline` ≠ `exe`** (process masquerading). List
open sockets per pid. All read-only.

## Persistence paths (phase 4)
cron/`at`, systemd units & **timers**, `~/.ssh/authorized_keys`, `ld.so.preload`, `rc.local`/profile
scripts, loaded kernel modules. Enumerate how the foothold survives a reboot.

## Docker capture (phase 5, non-destructive)
`docker pause <c>` then `docker commit <c> evidence:<ts>` and `docker export <c> > c.tar` — freeze
and snapshot a suspect container into a forensic image. **Capture, never `docker rm`.**

## Rootkit / audit scanners (phase 7, AFTER volatile capture)
- **chkrootkit**, **rkhunter** — known-rootkit signature scans.
- **Lynis** — host audit/hardening posture (also useful pre-incident as a baseline).

> Run these **last** and corroborate offline against the memory image / snapshot: an on-box rootkit
> can hide from these very tools. A clean live scan is not proof of a clean host.

Related: [[rfc-3227-ir-state-machine]] · [[vps-hardening-playbook]] · [[secret-remediation-reversibility]]
