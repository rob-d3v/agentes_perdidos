# Conventions for adding an agent

This file is for contributors (human or LLM) adding a new agent to the repo. It's also the
file a generic coding agent should read to understand the repo's structure.

## Anatomy of an agent

Every agent is a folder under `agents/<kebab-name>/` containing:

- **`SKILL.md`** (required) — the brain. YAML frontmatter (`name`, `description`) followed by:
  what the agent does, its **decision logic** (when to do what, with explicit rules/matrix),
  exact **commands to run**, the **workflow** when given a typical task, and gotchas.
  Write it so an LLM that has never seen the repo can execute correctly from this file alone.
- **Code** (optional) — scripts the agent runs. Python scripts use **`uv`** with PEP-723
  inline metadata (`# /// script ... ///`) so deps auto-install on `uv run` — no venv setup.
- **`README.md`** (optional) — human-facing quickstart.

## Rules

1. **`SKILL.md` frontmatter** must have `name` (matches folder) and a `description` that
   states when to use the agent and how it decides — this is what makes it trigger correctly.
2. **Secrets** go in `.env` only (gitignored). Add every new key to `.env.example` with a
   comment on where to get it. Never hardcode keys.
3. **Self-contained**: an agent should run from its folder given the repo `.env`. Don't depend
   on global state outside the repo (besides `uv` and the keys).
4. **Decision logic explicit**: if the agent chooses between options (providers, models,
   strategies), encode the rules as a table/matrix in `SKILL.md`, grounded in real tradeoffs.
   Research the options before writing the rules.
5. **Portable**: prefer instructions that work across LLM agents (Claude Code, Codex, etc.),
   not Claude-Code-only conventions, since this repo is meant to be shared.
6. **Register it**: add a row to the agents table in the root `README.md`.

## Python / uv pattern

```python
#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["some-pkg>=1.0"]
# ///
```

Run with: `uv run agents/<name>/script.py ...` — uv resolves and caches deps automatically.
