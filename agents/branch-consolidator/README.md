# branch-consolidator — the "MAIN" agent

Gets a repo consolidated onto its **real main** and prunes the dead branches AI coding sessions leave
behind — without losing work or breaking the deploy. **Protects the branch the VPS deploys from**
(never deleted/renamed), **never auto-deletes unmerged work** (surfaces it instead), and writes a
recovery tag + sha map before any deletion. Reversible by design.

Point an LLM at [`SKILL.md`](SKILL.md) and a target repo.

## Files
| File | Role |
|---|---|
| `SKILL.md` | the brain — deploy-branch detection, classification, the two unbreakable rules, workflow |
| `branchaudit.py` | **read-only** inventory: detect deploy branch + classify every branch + summarize unmerged work |
| `consolidate.py` | backup bundle + per-branch backup tags, then **safe** (`-d` only) delete of merged branches; dry-run by default |

## Quickstart
```bash
uv run branchaudit.py  /path/to/repo                     # read-only: what's there, what's safe, what's unmerged
uv run consolidate.py  /path/to/repo --deploy-branch main --dry-run   # what would be deleted
uv run consolidate.py  /path/to/repo --deploy-branch main --apply     # backup tags + delete merged branches
git branch <name> backup/<name>-<ts>                                  # recover a deleted branch
```

## Safety
- Deploy/main branch + current branch + any unmerged branch = **never deleted**.
- Only `git branch -d` (refuses non-merged) — force-delete is banned in the agent.
- Per-branch recovery **tags + a sha map** written **before** any delete (complete, since merged branches' commits stay in the deploy branch).
- Local-only by default; remote deletion is gated behind `--remote` + a re-confirm.
- Merging unmerged work into a deploy branch = a deploy → validate first, propose, never auto.

> Per-repo branch reports go into the target project's own brain (`./.branches/`), not this repo.
