---
title: Security + infra brain (front door)
type: overview
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, infra, overview, index, shared]
---

# Security + infra brain (front door)

This is the shared, **public, non-confidential** knowledge base of security + infra methodology that
the security agents load as hot context — generic doctrine, tool docs, and checklists that apply to
any project, living ONCE here and linked, never duplicated per project. Start here, then drill into
the page you need.

## Who consumes this
- **security-reviewer** — runs [[two-layer-security-review]] (deterministic [[scanner-stack]] + AI), maps findings to [[owasp-top-10-2021-mapping]] using the [[per-stack-owasp-checklist]].
- **architecture-auditor** — design-level review: [[webhook-signature-verification]], [[client-bundle-secret-leakage]], [[dependency-supply-chain-security]].
- **vps-hardener** — applies the [[vps-hardening-playbook]] under the [[hardening-reversibility-doctrine]], minding [[docker-bypasses-ufw]] + [[hardened-daemon-json]].
- **incident-responder** — runs the [[rfc-3227-ir-state-machine]] with [[ir-tooling]].

## Public / private split
> **Only generic methodology lives here** (this is the public `agentes_perdidos` repo). **No** server
> IPs, hostnames, secret values, `sk_live`, cert paths, or per-repo findings — ever. Confidential,
> fleet-specific findings live ONLY in the private brain. Links are one-way: private → shared.

## Index

### Security concepts
- [[owasp-top-10-2021-mapping]] — A01–A10 taxonomy every finding maps to.
- [[two-layer-security-review]] — deterministic CLI gate + AI reasoning layer.
- [[per-stack-owasp-checklist]] — ripgrep detection patterns per stack (incl. Next.js CVE-2025-29927).
- [[client-bundle-secret-leakage]] — why `VITE_/NEXT_PUBLIC_/EXPO_PUBLIC_` ship secrets to clients.
- [[secret-remediation-reversibility]] — rotate first, never auto-rewrite history.
- [[webhook-signature-verification]] — verify signature + idempotency before acting.
- [[dependency-supply-chain-security]] — A06 tooling, SBOM, triage by KEV/EPSS.

### Infra concepts
- [[hardening-reversibility-doctrine]] — 3-layer reversible change model.
- [[docker-bypasses-ufw]] — Docker ignores UFW; fix with ufw-docker / DOCKER-USER.
- [[rfc-3227-ir-state-machine]] — order-of-volatility incident response.

### Entities (tools & configs)
- [[scanner-stack]] — SAST + secret + dep scanners (SARIF).
- [[hardened-daemon-json]] — hardened Docker daemon + runtime flags.
- [[ir-tooling]] — UAC, AVML, /proc forensics, rootkit scanners.
- [[vps-hardening-playbook]] — reversible Ubuntu/Debian Docker-PaaS checklist.

Related: [[agentes-perdidos-agents]] · [[llm-wiki-pattern]]
