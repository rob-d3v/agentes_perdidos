---
title: VPS hardening playbook (Ubuntu/Debian Docker-PaaS)
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, hardening, vps, ssh, fail2ban, checklist, shared]
---

# VPS hardening playbook (Ubuntu/Debian Docker-PaaS)

The reversible hardening checklist for an Ubuntu/Debian host running a Docker PaaS (Coolify/Dokploy),
each item tagged **LOW-risk (auto-apply after snapshot)** or **HIGH-risk (propose + ask)** per the
[[hardening-reversibility-doctrine]]. Every change goes through the snapshot gate + generated
`rollback.sh`; lockout-class items get a watchdog.

## SSH — **HIGH-risk** (keep a 2nd session open!)
`/etc/ssh/sshd_config.d/99-hardening.conf`:
```
PasswordAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3
X11Forwarding no
```
`sshd -t` to validate, `systemctl reload ssh`, then **prove a fresh key-only login works in a second
terminal before closing the first**. Watchdog auto-revert armed.

## fail2ban — **LOW-risk**
Install; enable `sshd` jail and the **`recidive`** jail (bans repeat offenders longer). Confirm
`fail2ban-client status sshd`. (Gotcha: on a Docker host fail2ban's iptables actions interact with
Docker's chains — verify bans actually take.)

## unattended-upgrades — **LOW-risk (with Docker pin)**
Enable **security-only** auto-updates, but **pin/hold `docker-ce` and `containerd.io`** so an engine
major can't land unattended (see [[hardened-daemon-json]] engine-bump guard). Add them to
`Unattended-Upgrade::Package-Blacklist`.

## sysctl hardening — **LOW-risk** (one networking caveat)
`/etc/sysctl.d/99-hardening.conf`: rp_filter, `tcp_syncookies=1`, disable source routing &
`accept_redirects`, `kptr_restrict`, `dmesg_restrict`. **Never** set `net.ipv4.ip_forward=0` on a
Docker host — it kills container networking ([[docker-bypasses-ufw]]).

## auditd (CIS) — **LOW-risk**
Install `auditd` + a CIS-style ruleset (watch `/etc/passwd`, `/etc/sudoers`, `sshd_config`, sudo
calls). Feeds [[rfc-3227-ir-state-machine|incident response]] later.

## Service surface — **LOW/HIGH**
Disable `rpcbind` if NFS is unused (**LOW**). Audit listening ports (`ss -tlnp`) and close
unneeded ones (**HIGH** if any could be in use).

## Firewall — **HIGH-risk**
UFW does **not** cover Docker-published ports by default — use **ufw-docker** + `ufw route`
([[docker-bypasses-ufw]]), and layer the **cloud provider firewall** outside the host.

## Audit / verify
`lynis audit system` and `docker-bench-security` for a posture score before and after — confirm the
hardening landed and nothing regressed.

Related: [[hardening-reversibility-doctrine]] · [[docker-bypasses-ufw]] · [[hardened-daemon-json]] · [[ir-tooling]] · [[rfc-3227-ir-state-machine]]
