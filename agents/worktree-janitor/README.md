# worktree-janitor

Reclaim disk by deleting duplicated git **working trees**, never by deleting work.

Long AI-assisted development leaves worktrees behind: one per subagent, one per scratch topic, one
per tool-created `.claude/worktrees/<name>`. Each is a full checkout. Nothing ever lists them
across repositories, so the only visible symptom is a disk filling up — and the instinctive fix is
to reinstall the machine, which is the wrong tool for the problem.

## Use it

```bash
python worktrees.py scan            # classify everything, change nothing
python worktrees.py plan            # exactly what `clean` would remove
python worktrees.py clean           # remove merged worktrees, prune stale registrations
python worktrees.py clean --force   # also remove unmerged ones (quantified prompt)
```

Stdlib only, Python 3.8+. Default roots are `E:\backup_2026\Repositórios` and `D:\Repos`; override
with `--root`, repeatable.

## What the verdicts mean

- **green** — the branch is fully contained in `main`/`master`/`develop`, the tree is clean, there
  is no stash. Deleting it destroys nothing.
- **yellow** — a registration whose directory is already gone. `git worktree prune` territory; no
  code is at risk.
- **red** — unmerged commits, uncommitted changes, a stash, a detached HEAD, or an explicit lock.
  Never removed without `--force`, and `--force` prints the exact number of commits and modified
  files that would be lost before asking you to type a word.

Every row prints **why** it was classified that way. That is the part that makes the verdict
arguable, and an unauditable delete is just a delete you have not regretted yet.

## Relationship to `branch-consolidator`

They are complementary and ordered:

1. `worktree-janitor` removes the working trees.
2. `branch-consolidator` then evaluates the freed branches for deletion.

Running them the other way round does not work: a branch checked out in a live worktree cannot be
deleted, so the consolidator correctly skips it and the disk stays full.

See `SKILL.md` for the full contract, the safety rules, and why sizes are opt-in.
