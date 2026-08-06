---
title: Secret remediation — rotate first, never auto-rewrite history
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, secrets, remediation, doctrine, shared]
---

# Secret remediation — rotate first, never auto-rewrite history

A leaked secret is **burned the instant it's exposed** — assume it was scraped — so the only correct
order is **ROTATE first, then redact**; deleting the value from code changes nothing about the
already-leaked credential. Treat every secret-scanner hit as compromised, not as "we'll fix it before
anyone notices."

## The fixed order of operations
1. **Rotate / revoke** the credential at the provider (new key, invalidate old). This is the step
   that actually stops the bleed. Everything else is cleanup.
2. **Replace** the usage with a reference to a secret store / env var (never a new literal).
3. **Redact** the value from the current tree.
4. Only then consider history.

## Never auto-rewrite git history
Purging a secret from history (`git filter-repo`, BFG) **rewrites every commit hash and force-pushes**
— it breaks every clone, open PR, and fork, and silently de-syncs collaborators. An agent must
**never do this autonomously**:
> History rewrite is a **coordinated human operation**: announce a freeze, run `git filter-repo`,
> force-push, have everyone re-clone. And it's pointless without step 1 — the secret is already out,
> so rotation is what matters; history scrubbing only reduces residual exposure.

## Versioned suppression (baselines)
Acknowledge known/accepted findings explicitly so the gate stays green without weakening it:
- `detect-secrets scan > .secrets.baseline` (Apache-licensed; audit, then commit the baseline).
- `gitleaks detect --baseline-path gitleaks-report.json` to suppress already-triaged hits.
A baseline is **versioned, reviewable suppression** — a new real secret still trips the gate; an
accepted false positive doesn't re-alert. Never suppress without an audit note.

## Pin scanner versions
Pin `semgrep`, `gitleaks`, `trufflehog`, `detect-secrets` to exact versions in CI. A silent upstream
**rule update can change what the gate catches** between runs — pinning makes the gate reproducible
and rule changes an explicit, reviewed bump (a [[dependency-supply-chain-security|dependency PR]],
not an auto-merge).

Related: [[client-bundle-secret-leakage]] · [[scanner-stack]] · [[two-layer-security-review]] · [[hardening-reversibility-doctrine]]
