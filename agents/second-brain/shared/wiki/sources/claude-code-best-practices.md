---
title: Claude Code — Best Practices
type: source
created: 2026-06-14
updated: 2026-06-14
sources: [claude-code-best-practices]
tags: [claude-code, workflow, context, shared]
url: https://code.claude.com/docs/en/best-practices
---

# Claude Code — Best Practices

Distilled from the official guide. Most practices follow from one constraint: **context fills
fast and model performance degrades as it fills** — managing context is the core skill. See also
[[claude-code-context-management]].

## Verification — give Claude a check it can run
- Claude stops when work "looks done"; without a runnable check, *you* are the verification loop.
- Provide a pass/fail signal: test suite, build exit code, linter, fixture diff, browser screenshot.
- Gate strength, weakest→strongest: ask-and-iterate in one prompt → `/goal` condition → Stop hook → second-opinion verification subagent (fresh model tries to refute).
- Demand **evidence** (test output, command + result, screenshot), not assertions of success.
- Fix root causes, not symptoms; don't suppress errors.

## Explore → Plan → Code → Commit
- Don't jump straight to coding — you'll solve the wrong problem.
- **Explore** in plan mode (read, no edits) → **Plan** (detailed, editable via `Ctrl+G`) → **Implement** (verify against plan) → **Commit** (descriptive msg + PR).
- Skip planning when the diff fits in one sentence (typo, log line, rename). Plan when uncertain, multi-file, or unfamiliar code.

## Specific prompts beat vague ones
- Scope the task (which file, which scenario, test prefs). Point to sources (git history, example files). Reference existing patterns. Describe symptom + likely location + what "fixed" looks like.
- Provide rich context: `@file` references, pasted images/screenshots, URLs (allowlist domains), `cat x | claude`, or let Claude fetch what it needs.
- Vague prompts are fine for open-ended exploration you can course-correct.

## Environment / CLAUDE.md
- `CLAUDE.md` loads every session — keep it **short**; per line ask "would removing this cause mistakes?". Bloat makes Claude ignore real rules.
- Include: non-guessable bash commands, non-default style rules, test instructions, repo etiquette, project-specific architecture, env quirks, gotchas. Exclude: anything inferable from code, standard conventions, volatile info, long tutorials.
- `@path` imports; locations: `~/.claude/CLAUDE.md` (global), `./CLAUDE.md` (team), `./CLAUDE.local.md` (gitignored personal), parent/child dirs (monorepos).
- Emphasis ("IMPORTANT", "YOU MUST") improves adherence. Domain/sometimes-relevant knowledge → use **skills** (loaded on demand), not CLAUDE.md.

## Extensions — match feature to goal
- **Permissions**: auto mode (classifier approves), allowlists (`/permissions`), or `/sandbox` (OS isolation) to cut prompt fatigue.
- **CLI tools** (`gh`, `aws`, `gcloud`) are the most context-efficient way to hit external services; teach Claude unknown CLIs via `--help`.
- **MCP servers** for issue trackers, DBs, Figma, monitoring.
- **Hooks** = deterministic, guaranteed actions (e.g. lint after edit) — unlike advisory CLAUDE.md.
- **Skills** (`.claude/skills/<name>/SKILL.md`) = on-demand domain knowledge / repeatable workflows; `disable-model-invocation: true` for side-effecting ones.
- **Subagents** (`.claude/agents/`) = isolated context + scoped tools for read-heavy or specialized tasks.

## Session management
- Course-correct early: `Esc` (stop, keep context), `Esc Esc`/`/rewind` (restore state), "undo that", `/clear` (reset between unrelated tasks).
- Manage context aggressively: `/clear` between tasks, `/compact <focus>`, summarize-from/up-to via rewind, `/btw` for out-of-context side questions.
- **Subagents for investigation** — they read many files in a separate context and report summaries, keeping main context clean. Also for fresh-context review.
- Checkpoints snapshot files before each change (Claude's changes only — not a git replacement). Resume with `claude --continue` / `--resume`; name sessions like branches.

## Automate & scale
- Non-interactive: `claude -p "prompt"` (+ `--output-format json|stream-json --verbose`) for CI, hooks, pipelines.
- Parallel: worktrees, desktop sessions, web sessions, agent teams. Fresh context improves review (Writer/Reviewer pattern; tests-then-code).
- Fan out: generate task list → loop `claude -p` per file with `--allowedTools` → test on 2-3, then run at scale.
- Auto mode (`--permission-mode auto`) for unattended runs; aborts in `-p` if classifier repeatedly blocks.
- Adversarial review: fresh subagent reviews the diff vs the plan; tell it to flag only correctness/requirement gaps (a gap-hunter always finds some → over-engineering risk).

## Common failure patterns
- **Kitchen-sink session** → `/clear` between unrelated tasks.
- **Correcting over and over** → after 2 failed corrections, `/clear` + better prompt.
- **Over-specified CLAUDE.md** → prune ruthlessly; convert rules to hooks.
- **Trust-then-verify gap** → always provide verification; if you can't verify, don't ship.
- **Infinite exploration** → scope investigations or delegate to subagents.

Related: [[uv-pep723-pattern]] · [[llm-wiki-pattern]] · [[agentes-perdidos-agents]]
