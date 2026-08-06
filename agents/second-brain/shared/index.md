# shared — brain index

_21 pages · regenerated 2026-06-27._ Read this first; then open the page.

## Overview

- [[wiki/overview/security-infra-brain|Security + infra brain (front door)]] — This is the shared, public, non-confidential knowledge base of security + infra methodology that
- [[wiki/overview/agentes-perdidos-agents|agentes_perdidos — agents catalog]] — Public collection of self-contained AI agents.

## Entities

- [[wiki/entities/hardened-daemon-json|Hardened daemon.json + container runtime flags]] — A hardened /etc/docker/daemon.json plus least-privilege per-container runtime flags — the
- [[wiki/entities/ir-tooling|Incident-response tooling]] — The concrete tools that execute the [[rfc-3227-ir-state-machine]] — each entry says what it does
- [[wiki/entities/scanner-stack|Scanner stack (SAST + secrets + deps)]] — The concrete set of scanners that form the deterministic layer of [[two-layer-security-review]], each
- [[wiki/entities/vps-hardening-playbook|VPS hardening playbook (Ubuntu/Debian Docker-PaaS)]] — The reversible hardening checklist for an Ubuntu/Debian host running a Docker PaaS (Coolify/Dokploy),

## Concepts

- [[wiki/concepts/claude-code-context-management|Claude Code — Context Management]] — The context window holds the entire conversation: every message, every file read, every command
- [[wiki/concepts/client-bundle-secret-leakage|Client-bundle secret leakage (VITE_/NEXT_PUBLIC_/EXPO_PUBLIC_)]] — Any env var with a public prefix — VITE, NEXTPUBLIC, EXPOPUBLIC — is inlined as a
- [[wiki/concepts/dependency-supply-chain-security|Dependency & supply-chain security (OWASP A06)]] — [[owasp-top-10-2021-mapping|A06 Vulnerable & Outdated Components]] is handled by scanning declared
- [[wiki/concepts/docker-bypasses-ufw|Docker bypasses UFW (DOCKER-USER chain)]] — Docker writes its own iptables NAT and FORWARD rules and routes published-port traffic through the
- [[wiki/concepts/hardening-reversibility-doctrine|Hardening reversibility doctrine (3-layer reversible change)]] — Any infra hardening change must be reversible by construction through three layers, because the
- [[wiki/concepts/owasp-top-10-2021-mapping|OWASP Top 10 (2021) — finding mapping target]] — The OWASP Top 10 2021 categories (A01–A10) are the canonical taxonomy every security finding maps
- [[wiki/concepts/per-stack-owasp-checklist|Per-stack OWASP detection checklist (ripgrep patterns)]] — High-signal rg grep patterns to triage a codebase fast, grouped by stack — each line is a first
- [[wiki/concepts/rfc-3227-ir-state-machine|RFC 3227 incident-response state machine (order of volatility)]] — RFC 3227's rule governs IR: collect the most-volatile evidence first, read-only, before ANY
- [[wiki/concepts/secret-remediation-reversibility|Secret remediation — rotate first, never auto-rewrite history]] — A leaked secret is burned the instant it's exposed — assume it was scraped — so the only correct
- [[wiki/concepts/llm-wiki-pattern|The LLM-Wiki (second-brain) pattern]] — A way to build a personal/project knowledge base with an LLM (Karpathy's "LLM Wiki" idea, per
- [[wiki/concepts/two-layer-security-review|Two-layer security review (deterministic gate + AI reasoning)]] — A security review runs two complementary layers: a deterministic CLI gate (SAST + secret
- [[wiki/concepts/webhook-signature-verification|Webhook signature verification + idempotency]] — Every public / permitAll webhook endpoint MUST verify the provider's signature and enforce
- [[wiki/concepts/uv-pep723-pattern|uv + PEP-723 inline-script pattern]] — Every Python script in agentesperdidos is a single self-contained file with PEP-723 inline

## Sources

- [[wiki/sources/claude-code-best-practices|Claude Code — Best Practices]] — Distilled from the official guide.
- [[wiki/sources/karpathy-llm-wiki|Source: Karpathy — LLM Wiki idea file]] — The idea file that seeds the second-brain agent.
