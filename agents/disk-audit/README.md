# disk-audit

Finds what is eating a Windows disk and says what can be deleted safely. Walks a drive with a
junction-aware, long-path-aware scanner, ranks the biggest directories, and classifies every
finding as **SAFE** (regenerable — `node_modules`, build caches, package-manager caches),
**REVIEW** (build output, virtualenvs, bloated `.git`, WSL/Docker `.vhdx`, Windows junk, huge
loose files, duplicates) or **NEVER** (`pagefile.sys`, `WinSxS`, user data — reported for size
only). **Reporting is read-only**; removal is a separate armed command.

Point an LLM at [`SKILL.md`](SKILL.md) and a drive.

## Files
| File | Role |
|---|---|
| `SKILL.md` | the brain — risk matrix, category rules, workflow, Windows gotchas |
| `diskaudit.py` | the whole tool: `scan` / `caches` / `windows` / `repos` / `dupes` / `clean` / `selftest` |

Stdlib only, Python 3.10+, no `.env`, no credentials. Runs with plain `python` (or `uv run`)
from PowerShell and Git Bash.

## Quickstart
```bash
python diskaudit.py scan E:\ --depth 3 --dupes --json E:\audit.json --markdown E:\audit.md
python diskaudit.py scan C:\ --depth 3 --json C:\audit.json     # adds vhdx + Windows junk
python diskaudit.py caches           # every package-manager cache + how to clear it (fast)
python diskaudit.py windows          # Windows junk, WSL/Docker vhdx, pagefile (fast)
python diskaudit.py repos E:\Repos   # .git bloat ranking across a repo forest
python diskaudit.py selftest         # verify the guards + the ctypes struct; deletes nothing
```

Removal, only after reading the report:
```bash
python diskaudit.py clean --from E:\audit.json --category node_modules --dry-run
python diskaudit.py clean --from E:\audit.json --category node_modules --yes-delete-for-real
```
It prints the exact list and total, then requires you to type `DELETE`. It only accepts SAFE
categories, re-verifies every path, refuses protected locations, and logs each removal to a
timestamped `.jsonl` next to the report.

> ⚠️ `clean` recycles by default, but Windows deletes items larger than the Recycle Bin quota
> **permanently and silently**. Treat every run as irreversible.
