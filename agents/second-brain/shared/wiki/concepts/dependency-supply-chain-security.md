---
title: Dependency & supply-chain security (OWASP A06)
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, dependencies, supply-chain, a06, sbom, shared]
---

# Dependency & supply-chain security (OWASP A06)

[[owasp-top-10-2021-mapping|A06 Vulnerable & Outdated Components]] is handled by scanning declared
**and transitive** dependencies against known-vuln databases, then **triaging by exploitability** —
not by raw CVSS — and bumping via reviewed PRs, never auto-merge. The goal is to fix what's actually
reachable and exploitable, not to chase every advisory.

## Tooling matrix (by ecosystem)
| Ecosystem | Scanners |
|---|---|
| **Python** | `pip-audit` (PyPI advisory DB) · `safety` |
| **Node / npm** | `npm audit` · `osv-scanner` (Google OSV) · `retire.js` (vulnerable JS libs) |
| **Java (Gradle/Maven)** | OWASP **Dependency-Check** · **Trivy** |
| **Any / filesystem & images** | **Trivy** `fs --scanners vuln,secret,misconfig` (one tool: deps + secrets + IaC misconfig) · `osv-scanner` |

## SBOM (software bill of materials)
Generate an SBOM so you can answer "are we affected by CVE-X?" instantly: **syft** (`syft <dir> -o
cyclonedx-json`) or the **cyclonedx** CLIs. Feed the SBOM to a vuln scanner (`grype`, `trivy sbom`)
on a schedule, not just at build.

## Triage by exploitability (not raw CVSS)
A CVSS 9.8 in code you never call is lower priority than a 6.5 that's wormable and being exploited
now. Prioritize with:
- **CISA KEV** (Known Exploited Vulnerabilities) — if it's on KEV, it's being exploited in the wild → top priority.
- **EPSS** (Exploit Prediction Scoring System) — probability of exploitation in the next 30 days.
- **Reachability** — is the vulnerable function actually called from your code path?

CVSS is severity-if-exploited; KEV+EPSS+reachability is likelihood-of-exploit. Rank by the latter.

## Process
- **Dependency bumps are PR-only — never auto-merged.** A version bump is a code change with its own
  risk (breaking change, malicious package). Review the diff and changelog. Pin scanner versions too
  (see [[secret-remediation-reversibility]]).
- Automate the *proposing* with **Dependabot** or **Renovate** (grouped PRs, scheduled, with a
  human approval gate). Let the bot open the PR; a human merges.

Related: [[owasp-top-10-2021-mapping]] · [[scanner-stack]] · [[secret-remediation-reversibility]] · [[two-layer-security-review]]
