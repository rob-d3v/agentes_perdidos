#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
branchaudit.py — READ-ONLY branch inventory + classification for the branch-consolidator agent.

Detects the real-main / deploy branch, then classifies every local + remote branch as
protected / merged (safe to delete) / unmerged-with-work (surface, never auto-delete) / stale,
and summarizes the unique commits on each unmerged branch so a human can decide. Changes NOTHING.

Every git call runs with GIT_TERMINAL_PROMPT=0 + a timeout so a credential prompt or a huge repo
can't hang the run.

Usage:  uv run branchaudit.py <repo> [--deploy-branch main] [--json]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "GCM_INTERACTIVE": "never"}
HEURISTIC = ["main", "master", "production", "deploy", "release"]


def git(root: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           env=ENV, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return 124, ""
    except FileNotFoundError:
        return 127, ""


def find_git_root(path: Path) -> Path | None:
    if (path / ".git").exists():
        return path
    for sub in sorted(path.glob("*")):
        if sub.is_dir() and (sub / ".git").exists():
            return sub
    return None


def local_branches(root: Path) -> list[str]:
    rc, out = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return [b for b in out.splitlines() if b] if rc == 0 else []


def remote_branches(root: Path) -> list[str]:
    rc, out = git(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes")
    return [b for b in out.splitlines() if b and not b.endswith("/HEAD")] if rc == 0 else []


def detect_deploy_branch(root: Path, override: str | None, locals_: list[str]) -> tuple[str, str]:
    if override:
        return override, "explicit --deploy-branch"
    rc, out = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        return out.split("/", 1)[-1], "origin/HEAD (remote default)"
    for name in HEURISTIC:
        if name in locals_:
            return name, f"name heuristic ({name})"
    rc, cur = git(root, "branch", "--show-current")
    if rc == 0 and cur:
        return cur, "current HEAD (fallback — CONFIRM before deleting)"
    return "main", "default guess (CONFIRM)"


def merged_into(root: Path, main: str) -> set[str]:
    rc, out = git(root, "branch", "--merged", main)
    if rc != 0:
        return set()
    merged = set()
    for ln in out.splitlines():
        s = ln.strip()
        if not s or s.startswith("+"):   # skip blanks + worktree-held branches (in use)
            continue
        merged.add(s.lstrip("*").strip())
    return merged


def unique_commits(root: Path, main: str, branch: str) -> list[dict]:
    rc, out = git(root, "log", "--no-merges", "--pretty=%h|%ad|%s", "--date=short",
                  f"{main}..{branch}", "-n", "25")
    if rc != 0 or not out:
        return []
    rows = []
    for ln in out.splitlines():
        parts = ln.split("|", 2)
        if len(parts) == 3:
            rows.append({"sha": parts[0], "date": parts[1], "subject": parts[2][:100]})
    return rows


def is_squash_equivalent(root: Path, main: str, branch: str) -> bool:
    # git cherry: every line starting with '-' means an equivalent commit is already in main
    rc, out = git(root, "cherry", main, branch)
    if rc != 0 or not out:
        return True
    return all(ln.startswith("-") for ln in out.splitlines() if ln.strip())


def gone_upstream(root: Path) -> set[str]:
    rc, out = git(root, "branch", "-vv")
    gone = set()
    if rc == 0:
        for ln in out.splitlines():
            if ": gone]" in ln:
                gone.add(ln.replace("*", "").strip().split()[0])
    return gone


def classify(root: Path, main: str, current: str) -> dict:
    locals_ = local_branches(root)
    remotes = remote_branches(root)
    merged = merged_into(root, main)
    gone = gone_upstream(root)
    protected, safe_delete, surface, stale = [], [], [], []

    for b in locals_:
        if b == main or b == current:
            protected.append({"branch": b, "why": "deploy/main or current HEAD"})
            continue
        if b in merged:   # cheap path — already an ancestor of main, no per-branch git ops needed
            (stale if b in gone else safe_delete).append({"branch": b, "merged": True, "gone": b in gone})
            continue
        # non-merged: ONE fast ancestry count; only branches with unique commits get the (slower) sample
        rc, cnt = git(root, "rev-list", "--count", f"{main}..{b}", timeout=20)
        n = int(cnt) if cnt.isdigit() else -1
        if n == 0:   # equivalent to main by ancestry (e.g. squash-merged) → safe
            (stale if b in gone else safe_delete).append({"branch": b, "merged": "equivalent", "gone": b in gone})
        else:
            uniq = unique_commits(root, main, b)
            surface.append({"branch": b, "unique_commits": (n if n >= 0 else len(uniq)),
                            "gone": b in gone, "sample": uniq[:8]})
    return {
        "main": main, "current": current,
        "counts": {"local": len(locals_), "remote": len(remotes),
                   "protected": len(protected), "safe_delete": len(safe_delete),
                   "surface_unmerged": len(surface), "stale_gone": len(stale)},
        "protected": protected, "safe_delete": safe_delete,
        "surface_unmerged": surface, "stale_gone": stale,
        "remote_branches": remotes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--deploy-branch", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = find_git_root(Path(args.repo).resolve())
    if not root:
        print(json.dumps({"error": "no git repo found", "path": args.repo}))
        return 2
    rc, current = git(root, "branch", "--show-current")
    locals_ = local_branches(root)
    main_branch, how = detect_deploy_branch(root, args.deploy_branch, locals_)
    result = {"repo": str(root), "deploy_branch_detected": main_branch, "detection": how}
    result.update(classify(root, main_branch, current))

    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    c = result["counts"]
    print(f"# {root.name}: real-main = '{main_branch}'  ({how})")
    print(f"  local={c['local']} remote={c['remote']}  | protected={c['protected']} "
          f"safe-delete={c['safe_delete']} unmerged-surface={c['surface_unmerged']} stale-gone={c['stale_gone']}")
    if result["safe_delete"] or result["stale_gone"]:
        print("\n## Safe to delete (merged into main - content preserved):")
        for x in result["safe_delete"] + result["stale_gone"]:
            print(f"   - {x['branch']}" + ("  [upstream gone]" if x.get('gone') else ""))
    if result["surface_unmerged"]:
        print("\n## [!] Unmerged - has unique work, DO NOT auto-delete (decide: merge / keep / drop):")
        for x in result["surface_unmerged"]:
            print(f"   - {x['branch']}  ({x['unique_commits']} unique commits)")
            for cm in x["sample"]:
                print(f"       {cm['date']} {cm['sha']} {cm['subject']}")
    print("\n(read-only audit - nothing changed. Next: consolidate.py --dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
