---
title: security-reviewer agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/security-reviewer/SKILL.md]
tags: [agent, security, sast, secrets, dependencies, sarif]
---

Two-layer **application-security review** for any repo: a deterministic CLI scanner gate the LLM cannot be prompt-injected out of, plus an AI reasoning core for the logic bugs pattern-matchers miss.

## The two layers (in order)
1. **Deterministic gate (authoritative, blocking).** Semgrep (`p/security-audit` + `p/owasp-top-ten` + `p/secrets`) + Gitleaks (working tree **and** full git history), all normalized to **SARIF** and merged. Opt-in language-native passes (Bandit / gosec / eslint-security / njsscan), a dependency / supply-chain pass (pip-audit / osv-scanner / npm audit / Trivy / OWASP Dependency-Check), and `buildscan.py` — a **built-artifact secret scan** (dist/, `.next/static`, extracted APK) that catches `VITE_`/`NEXT_PUBLIC_`/`EXPO_PUBLIC_` keys inlined into the shipped bundle.
2. **AI reasoning (triage + logic bugs).** Reuses Anthropic's MIT `claude-code-security-review` prompt (3-phase, confidence ≥ 0.8 gate, 18-item false-positive exclusion list, diff-aware) over the git diff + merged SARIF digest; traces dataflow input→sink to find auth bypass, IDOR, SSRF, missing webhook-signature verification.

## Modes (`secreview.py`)
`full <repo>` (first-pass audit) · `diff --base origin/main` (gate a change) · `secrets` (source + history) · `deps` (supply chain) · `buildscan.py` (shipped bundle) · `--deep` (semantic dataflow, public repos only). Ships per-stack OWASP Top-10 ripgrep checklists (Spring Boot / FastAPI / React-Vite / Next / RN-Expo / Node-Express / JavaFX) in `owasp_grep.py` + `prompts/`.

## Hard contract
**Read-only on source** — scanners write only to a gitignored reports dir; any fix is a proposed diff/PR the human reviews, never an in-place rewrite, never an automatic history rewrite. Per [[lost-agent-rule]], per-repo findings go in the **target project's own brain**; the methodology lives once in the [[shared-base-model|shared base]].

Part of the quality/security quartet with [[architecture-auditor]], [[performance-engineer]], [[clean-refactorer]]. Key files: `agents/security-reviewer/{SKILL.md,secreview.py,buildscan.py,owasp_grep.py,prompts/}` (run via [[uv]]). See [[agentes-perdidos]].
