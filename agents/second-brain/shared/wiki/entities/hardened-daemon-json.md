---
title: Hardened daemon.json + container runtime flags
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, docker, hardening, runtime, shared]
---

# Hardened daemon.json + container runtime flags

A hardened `/etc/docker/daemon.json` plus least-privilege per-container runtime flags — the
host-engine and container layers of Docker hardening. **Validate before restart**, and mind the
PaaS caveats (Coolify/Dokploy control planes break under some of these). Firewall interaction is in
[[docker-bypasses-ufw]].

## /etc/docker/daemon.json
```json
{
  "no-new-privileges": true,
  "icc": false,
  "userland-proxy": false,
  "live-restore": true,
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
```
- `no-new-privileges` — containers can't gain privileges via setuid binaries.
- `icc:false` — disable inter-container comm on the default bridge (force explicit networks).
- `userland-proxy:false` — drop the slow userland proxy; use iptables hairpin.
- `live-restore:true` — containers keep running across a dockerd restart (safer engine upgrades).

**`userns-remap` caveat:** user-namespace remapping is strong isolation but **breaks bind-mount
ownership and PaaS control-plane hosts** (Coolify/Dokploy manage containers as the engine sees
them). Don't enable it on a PaaS control node without testing.

## Validate BEFORE restart
```bash
sudo dockerd --validate      # parses daemon.json without applying — catches typos
sudo systemctl reload docker # or restart; live-restore protects running containers
```
A malformed `daemon.json` makes dockerd fail to start — `--validate` first, always.

## Least-privilege runtime flags
Run untrusted/public containers minimally privileged:
```bash
docker run \
  --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --security-opt no-new-privileges \
  --read-only --tmpfs /tmp \
  --pids-limit 200 --memory 512m --cpus 1 \
  --user 10001:10001 \
  myimage
```
Drop all caps then add back only what's needed; read-only rootfs + tmpfs for writable paths;
pids/memory/cpu limits to contain a runaway or fork-bomb; **non-root user**.

## Engine major-bump guard
**Pin `docker-ce` and `containerd.io`** in apt (and in [[vps-hardening-playbook|unattended-upgrades]]
exclusions). A Docker **Engine major bump (e.g. v29)** changed bundled-component behavior and broke
the bundled **Traefik** integration on some PaaS — treat engine majors as a reviewed, snapshotted
upgrade, not an unattended one.

Related: [[docker-bypasses-ufw]] · [[vps-hardening-playbook]] · [[hardening-reversibility-doctrine]]
