---
title: RFC 3227 incident-response state machine (order of volatility)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, incident-response, forensics, rfc-3227, doctrine, shared]
---

# RFC 3227 incident-response state machine (order of volatility)

RFC 3227's rule governs IR: **collect the most-volatile evidence first, read-only, before ANY
containment or rebuild** — the moment you reboot, `docker rm`, or reinstall, you destroy the RAM,
live processes, and network state that prove what happened. The phases below run in order; each is
non-destructive until the evidence is captured.

## Phases (in order)
- **0 — Declare & record.** Open the incident, start chain-of-custody, timestamp everything (note clock skew), assign one lead. Nothing touched yet.
- **1 — Snapshot & isolate.** Take a cloud snapshot; network-isolate (security-group/NSG cut, or `ip link set down` on a spare path). **Never reboot, never `docker rm`** — that's evidence destruction.
- **2 — RAM capture.** Acquire physical memory with **AVML** (static binary, no kernel headers) or **LiME**. RAM holds injected code, decrypted keys, and connections that vanish on reboot.
- **3 — /proc live triage.** Read-only walk of `/proc`: processes whose `exe` is `(deleted)`, `cwd` in `/tmp` or `/dev/shm`, mismatched `comm` vs `cmdline` vs `exe`, open sockets. Classic malware tells.
- **4 — Persistence sweep.** cron/at, systemd units & timers, `~/.ssh/authorized_keys`, `ld.so.preload`, rc/profile scripts, kernel modules — how they'd survive a reboot.
- **5 — Docker capture (non-destructive).** `docker pause <c>` then `docker commit` + `docker export` a suspect container to a forensic image — **capture, don't delete**.
- **6 — Logs.** Pull `journald` (`journalctl -o export`) and cross-check tampered `/var/log` (attackers truncate text logs but miss the journal). Grab the **fail2ban** ban list and auth logs.
- **7 — Rootkit scans (last).** `chkrootkit`/`rkhunter`/`lynis` run **after** volatile capture: rootkits **lie to live tools**, so corroborate offline against the snapshot/memory image — don't trust an on-box scan as ground truth.

## Image-vs-rebuild decision
Rebuild from a **known-good** image only **after** all three hold: (1) evidence captured, (2) root
cause understood (so you don't redeploy the same hole), (3) **ALL secrets rotated** (assume the
attacker read every credential on the box — see [[secret-remediation-reversibility]]). Rebuilding
before that destroys evidence and re-exposes the same secrets.

Tooling specifics in [[ir-tooling]]. Containment changes follow
[[hardening-reversibility-doctrine|reversibility doctrine]].

Related: [[ir-tooling]] · [[hardening-reversibility-doctrine]] · [[secret-remediation-reversibility]] · [[vps-hardening-playbook]]
