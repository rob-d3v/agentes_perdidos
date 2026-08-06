---
title: uv + PEP-723 inline-script pattern
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: []
tags: [python, uv, tooling, shared]
---

# uv + PEP-723 inline-script pattern

Every Python script in `agentes_perdidos` is a single self-contained file with **PEP-723 inline
metadata** in a comment block, run via [`uv`](https://docs.astral.sh/uv/). `uv` reads the block,
resolves + caches the deps, and runs the script — **no venv, no `pip install`, no setup**.

```python
#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["some-pkg>=1.0"]
# ///
"""docstring with usage"""
```

Run: `uv run agents/<name>/script.py <args>`.

## Why
- Zero-setup: a fresh machine with only `uv` installed runs any agent script.
- Self-documenting deps travel **with** the script, not in a separate requirements file.
- Reproducible: pinned `requires-python` + version specifiers.

## Convention here
- Prefer **stdlib-only** for helpers that must run offline (e.g. `secondbrain.py`, `dependencies = []`).
- Secrets come from the repo `.env` (gitignored), never hardcoded. See [[agentes-perdidos-agents]].

Related: [[claude-code-best-practices]] · [[agentes-perdidos-agents]]
