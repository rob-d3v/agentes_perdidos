# security-reviewer

Two-layer app-security review for any repo: a deterministic CLI gate (Semgrep + Gitleaks → SARIF,
plus opt-in language-native SAST, a dependency/supply-chain pass, and a built-artifact secret scan)
followed by an AI reasoning layer (Anthropic's `claude-code-security-review` prompt: 3-phase,
≥0.8 confidence, 18-item exclusion list) that finds the logic bugs SAST misses. **Read-only on
source** — scanners write only to a gitignored `reports/` dir; fixes are PR-only.

Point an LLM at [`SKILL.md`](SKILL.md) and a target repo.

## Files
| File | Role |
|---|---|
| `SKILL.md` | the brain — modes, the two-layer pipeline, per-stack OWASP checklist, decision logic |
| `secreview.py` | Layer-1 orchestrator: runs available scanners, normalizes to SARIF, merges → `reports/_digest.json` |
| `buildscan.py` | scans the **shipped build artifact** (dist/.next/APK) for inlined `VITE_*`/`NEXT_PUBLIC_*`/`EXPO_PUBLIC_*` secret leakage |
| `owasp_grep.py` | per-stack OWASP Top-10 ripgrep-style candidate finder (stdlib; redacts secret hits) |
| `prompts/claude-code-security-review.md` | the Layer-2 AI reasoning prompt (adapted from Anthropic, MIT) |

## Quickstart
```bash
uv run secreview.py full    /path/to/repo          # first full audit
uv run secreview.py diff    /path/to/repo --base origin/main   # gate a change
uv run secreview.py secrets /path/to/repo          # secret hunt (tree + git history)
uv run buildscan.py        /path/to/repo --dist dist           # bundle leak scan
uv run owasp_grep.py       /path/to/repo --json     # OWASP candidates for the AI layer
```

Install the external scanners it shells out to (all optional, skipped-with-note if absent):
`semgrep`, `gitleaks`, `trufflehog`, `trivy`, `osv-scanner`, `pip-audit`, `bandit`, `detect-secrets`.

> Per-repo findings are **confidential** → written into the target project's own brain
> (`./.security/` or its Obsidian vault), never into this public repo. See `SKILL.md` → *Persisting findings*.
