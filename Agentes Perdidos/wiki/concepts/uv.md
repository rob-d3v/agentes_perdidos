---
title: uv / PEP-723 run pattern
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: [AGENTS.md]
tags: [uv, python, pep723, shared]
---

Every Python helper in [[agentes-perdidos]] runs with **`uv`** using PEP-723 inline script metadata — deps auto-install on `uv run`, no venv setup.

```python
#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["some-pkg>=1.0"]
# ///
```
Run with `uv run agents/<name>/script.py …`; uv resolves and caches deps automatically. (Note: `secondbrain.py` is stdlib-only, so it also runs under plain `python`.)

This is a generic pattern — full details live in the shared base: `agents/second-brain/shared/wiki/concepts/uv-pep723-pattern.md`. Linked here, not duplicated (see [[shared-base-model]]).
