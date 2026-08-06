---
title: Docker bypasses UFW (DOCKER-USER chain)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [infra, docker, firewall, ufw, networking, shared]
---

# Docker bypasses UFW (DOCKER-USER chain)

Docker writes its own iptables NAT and FORWARD rules and routes published-port traffic through the
**FORWARD** chain **before** UFW's **INPUT** rules ever see it — so `ufw deny <port>` does **NOT**
protect a Docker-published port. A container started with `-p 8080:80` is reachable from the internet
no matter what UFW says. This is the single most common "my firewall is on but the port is open" trap
on Docker PaaS hosts.

## Why
UFW only governs the INPUT chain. Docker publishes ports by inserting `DNAT` rules in the `nat` table
and accept rules in `DOCKER`/`FORWARD` — a separate path. The packet is forwarded to the container
before INPUT/UFW is consulted, so UFW's policy is irrelevant to published ports.

## The fix — ufw-docker (chaifeng)
Use `ufw-docker` to insert rules into the **`DOCKER-USER`** chain (the hook Docker leaves for the
operator), via `/etc/ufw/after.rules`:
```bash
sudo wget -O /usr/local/bin/ufw-docker \
  https://github.com/chaifeng/ufw-docker/raw/master/ufw-docker
sudo chmod +x /usr/local/bin/ufw-docker
sudo ufw-docker install      # writes DOCKER-USER rules into after.rules
sudo systemctl restart ufw
# then allow per container/port via the route table:
sudo ufw route allow proto tcp from any to any port 443
```
On modern Ubuntu prefer the **`ufw route`** sub-command (`ufw-user-forward` chain) to manage
container reachability — it's the supported path for forwarded traffic.

## What NOT to do
- **Never set `"iptables": false`** in `/etc/docker/daemon.json`. Docker stops managing rules,
  container networking breaks, and **Coolify/Dokploy and similar PaaS control planes break** with it.
- **Never `net.ipv4.ip_forward=0`** on a Docker host — Docker needs forwarding; disabling it kills
  all container networking.
- Don't rely on `ufw deny` alone for published ports — it's a false sense of security.

## Defense in depth — outer layer
The host firewall is layer 2. Put the **cloud provider's network firewall** (AWS security group,
Oracle/GCP security list, Azure NSG) as the **outer** layer: it filters at the virtual NIC, before
the packet reaches the host or Docker's iptables — so a Docker rule can't punch through it. Combine:
provider firewall (outer) + ufw-docker (host) + least-privilege container flags
([[hardened-daemon-json]]).

Related: [[hardened-daemon-json]] · [[vps-hardening-playbook]] · [[hardening-reversibility-doctrine]]
