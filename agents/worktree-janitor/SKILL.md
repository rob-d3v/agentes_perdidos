---
name: worktree-janitor
description: >
  Finds and safely removes the git worktrees that long AI-assisted sessions leave behind, to
  reclaim disk WITHOUT losing unmerged work and without reinstalling the machine. Sweeps every
  repository under one or more roots, lists every linked worktree (including the `.claude/worktrees/`
  ones that coding tools create per subagent and never clean up), and classifies each as green
  (branch fully merged + clean tree — safe to delete), yellow (stale registration whose directory is
  gone — `git worktree prune` territory, no code at risk) or red (unmerged commits, uncommitted
  changes, a stash, or detached HEAD — never deleted without an explicit, quantified confirmation).
  Dry-run by default; every row prints the reason for its classification so the verdict can be
  argued with. Use when disk is filling up, when `git worktree list` is full of ghosts, when a repo
  directory listing has more `*-wt-*` siblings than actual projects, or before considering a format
  or a fresh clone. Complements branch-consolidator, which deletes BRANCHES; this one deletes the
  WORKING TREES those branches were checked out into.
---

# worktree-janitor — the disk you already own

You reclaim space by deleting *duplicated working trees*, never by deleting work.

The situation this exists for: a workspace with 149 directories, of which ~80 are not projects at
all but worktrees — `AniaAPP-wt-voz`, `market-machine-hermes-sessao`, `theAPIAniaAPP-wt-ledger`,
and 26 machine-named ones under `.claude/worktrees/`. Each is a full checkout of a repository.
Nobody created them carelessly; each had a reason at the time. The failure is that **nothing ever
listed them together**, so the only visible symptom was a disk filling up, and the instinctive fix
was to reinstall the machine.

> **Two unbreakable rules.**
> 1. **The main checkout is never a candidate.** Not with `--force`, not ever.
> 2. **Red is never removed silently.** If work would be destroyed, the exact count of unmerged
>    commits and modified files is printed first, and the operator types a word to confirm.

## How to run it

```bash
python worktrees.py scan                 # classify everything, change nothing
python worktrees.py scan --sizes         # ...and measure disk (slow: walks every tree)
python worktrees.py plan                 # exactly what `clean` would do
python worktrees.py clean                # remove green, prune yellow
python worktrees.py clean --force        # also remove red (prompts, quantified)
python worktrees.py clean --only wt-i18n # limit to matching paths
python worktrees.py scan --root /srv/repos --root ~/code
```

Default roots are `E:\backup_2026\Repositórios` and `D:\Repos`. Override with `--root`, repeatable.

## The classification, and why each rule exists

| | Meaning | Test | Risk |
|---|---|---|---|
| **green** | Safe to delete | `git rev-list --count <target>..<branch>` is 0, `git status --porcelain` empty, `git stash list` empty | None. The commits exist in the integration branch. |
| **yellow** | Stale registration | `prunable` in `git worktree list --porcelain`, or the directory is gone | None. This is bookkeeping, not code. |
| **red** | Hands off | unmerged commits, dirty tree, stash, detached HEAD, or `locked` | Real. Deleting loses work that exists nowhere else. |

Integration branch is the first of `main`, `master`, `develop` that exists. If none exists, the
worktree is red — not green — because "I could not check" must never read as "it is fine".

A detached HEAD is red even when it looks clean: you cannot prove its commits are reachable from
any branch, and an unreachable commit is one `gc` away from gone.

A `locked` worktree is red regardless of its contents. Someone ran `git worktree lock` deliberately;
overriding that is not this tool's call.

## Reading the output

Every row carries `[OK ]` / `[REG]` / `[!! ]`, the repository, the branch, the size, the path, and
**the reason**. The reason is the point. A janitor that says "safe" without saying why cannot be
audited, and an unauditable delete is just a delete you have not regretted yet.

State is never carried by colour alone — the marker, the wording and the ordering all agree — so
the output survives a monochrome terminal, a log file and a screenshot.

## What it does not do

- It does not delete branches. That is `branch-consolidator`, and it should run *after* this one:
  removing a worktree frees its branch to be evaluated for deletion.
- It does not merge anything. A red worktree is surfaced, never resolved.
- It does not touch the object store. Removing a worktree reclaims the working files; run
  `git gc` yourself if you also want the objects compacted.
- It does not run `git worktree prune` on repositories it did not otherwise touch.

## Ordering that matters

`clean` removes worktrees first and prunes registrations afterwards, per repository. Pruning first
would drop the registration of a directory that is about to be removed, and `git worktree remove`
would then refuse it as unknown — leaving the directory on disk with nothing pointing at it, which
is the exact mess this tool exists to end.

## Sizes are opt-in

Measuring means `os.walk` over every tree. On ~80 worktrees on a mechanical drive that is minutes,
and a tool that appears to hang gets killed. Classification alone is only git calls. Ask for
`--sizes` when the question is "how much do I get back", which is a question you only have after
you know what is removable.
