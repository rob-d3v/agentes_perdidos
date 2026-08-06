---
title: Scanner stack (SAST + secrets + deps)
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, scanners, sast, secrets, tooling, shared]
---

# Scanner stack (SAST + secrets + deps)

The concrete set of scanners that form the deterministic layer of [[two-layer-security-review]], each
with purpose / license / install / one gate command — all normalized to **SARIF** so findings merge
across tools and into GitHub code-scanning. Pin versions (see [[secret-remediation-reversibility]]).

## SAST (static analysis)
| Tool | Purpose | License | Install | Gate command |
|---|---|---|---|---|
| **Semgrep CE** | multi-lang pattern + light taint SAST | LGPL | `pipx install semgrep` | `semgrep --config p/security-audit --config p/owasp-top-ten --sarif -o semgrep.sarif` |
| **OpenGrep** | community Semgrep fork; **intrafile taint** | LGPL | release binary | `opengrep scan --config auto --sarif -o opengrep.sarif` |
| **Bandit** | Python SAST | Apache-2.0 | `pipx install bandit` | `bandit -r . -f sarif -o bandit.sarif` |
| **gosec** | Go SAST | Apache-2.0 | `go install github.com/securego/gosec/v2/cmd/gosec@latest` | `gosec -fmt sarif -out gosec.sarif ./...` |
| **eslint-plugin-security** | JS/TS SAST | Apache-2.0 | `npm i -D eslint-plugin-security` | `eslint --format @microsoft/sarif` |
| **njsscan** | Node.js SAST | LGPL | `pipx install njsscan` | `njsscan --sarif -o njsscan.sarif .` |
| **CodeQL** | deep dataflow SAST | license-restricted (free OSS / GH only) | GH Action | **opt-in** — restrictions on commercial/closed use |

## Secrets
| Tool | Purpose | License | Install | Gate command |
|---|---|---|---|---|
| **Gitleaks** | regex secrets, tree + **history**, SARIF | MIT | release binary / `brew install gitleaks` | `gitleaks detect --redact --report-format sarif --report-path gitleaks.sarif` |
| **TruffleHog** | 800+ types, **verified** (live-creds API check); no SARIF → run as **separate process** | AGPL | release binary | `trufflehog git file://. --only-verified --json` |
| **detect-secrets** | **baseline** for legacy onboarding | Apache-2.0 | `pipx install detect-secrets` | `detect-secrets scan > .secrets.baseline` |

> **TruffleHog is AGPL** — keep it in its own process/container, don't import it into a differently
> licensed codebase. Its `--only-verified` mode cuts noise by making safe read-only API calls to
> confirm a secret is live.

## Dependencies / SBOM / mobile
- Deps (see [[dependency-supply-chain-security]]): `pip-audit`, `osv-scanner`, OWASP **Dependency-Check**, **Trivy** `fs --scanners vuln,secret,misconfig`.
- **MobSF** — static+dynamic analysis for Android/iOS apps (APK/IPA), incl. extracted-bundle secret scan.

## Why SARIF
SARIF (Static Analysis Results Interchange Format) is the JSON lingua franca: every tool above (or a
converter) emits it, so you **merge results, dedupe, and upload once** to GitHub code-scanning.
TruffleHog (no SARIF) is the deliberate exception — separate process, JSON, verified-only.

Related: [[two-layer-security-review]] · [[secret-remediation-reversibility]] · [[dependency-supply-chain-security]] · [[client-bundle-secret-leakage]]
