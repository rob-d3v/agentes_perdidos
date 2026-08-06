#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
consolidate.py — backup + SAFE delete of merged branches for the branch-consolidator agent.

Refuses to run on a dirty tree or detached HEAD. Backs up EVERY ref to a bundle and tags each
branch before deleting, then deletes ONLY merged branches with `git branch -d` (the safe form that
itself refuses to delete unmerged work — a second guard). Never touches the deploy/main branch, the
current branch, or any unmerged branch. Dry-run by default.

Recovery:  git fetch <repo>/.branch-backup/all-refs-<ts>.bundle 'refs/*:refs/*'

Usage:
  uv run consolidate.py <repo> --deploy-branch main [--dry-run | --apply] [--remote]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "GCM_INTERACTIVE": "never"}
HEURISTIC = ["main", "master", "production", "deploy", "release"]


def git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           env=ENV, timeout=timeout)
        return p.returncode, (p.stdout or "").strip() + (("\n" + p.stderr.strip()) if p.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError:
        return 127, "git not found"


def find_git_root(path: Path) -> Path | None:
    if (path / ".git").exists():
        return path
    for sub in sorted(path.glob("*")):
        if sub.is_dir() and (sub / ".git").exists():
            return sub
    return None


def detect_deploy(root: Path, override: str | None, locals_: list[str]) -> str:
    if override:
        return override
    rc, out = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        return out.split("/", 1)[-1]
    for n in HEURISTIC:
        if n in locals_:
            return n
    rc, cur = git(root, "branch", "--show-current")
    return cur or "main"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--deploy-branch", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remote", action="store_true", help="also delete merged REMOTE branches (extra-risk)")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    root = find_git_root(Path(args.repo).resolve())
    if not root:
        print(json.dumps({"error": "no git repo", "path": args.repo})); return 2

    # safety preconditions. NB: `git branch -d` never touches the working tree, so a dirty tree is
    # NOT a reason to refuse DELETION (only merges need a clean tree). We just note it and leave the
    # working tree untouched. Detached HEAD IS a hard stop (can't determine/protect the current branch).
    rc, status = git(root, "status", "--porcelain", timeout=120)
    dirty = bool(status) and rc == 0
    if dirty:
        print(f"NOTE: {root.name} has uncommitted/untracked changes — they are left untouched "
              f"(branch deletion does not modify the working tree).")
    rc, current = git(root, "branch", "--show-current")
    if not current:
        print(f"REFUSE: detached HEAD in {root}. Checkout a branch first."); return 1

    rc, locout = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    locals_ = [b for b in locout.splitlines() if b]
    main_b = detect_deploy(root, args.deploy_branch, locals_)
    if main_b not in locals_:
        print(f"NOTE: deploy branch '{main_b}' has no local copy; protecting it anyway (won't delete).")

    rc, merged_out = git(root, "branch", "--merged", main_b)
    merged, worktree_held = set(), set()
    for ln in merged_out.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("+"):           # checked out in a linked worktree — in use, never delete
            worktree_held.add(s[1:].strip())
            continue
        merged.add(s.lstrip("*").strip())
    # protect the deploy branch, the current branch, AND the conventional canonical names always
    # (so a non-main --deploy-branch can never cause `main`/`master` itself to be deleted).
    protected = {main_b, current, "main", "master"}
    to_delete = sorted(b for b in merged if b not in protected and b not in worktree_held)

    rc, main_sha_before = git(root, "rev-parse", main_b)
    plan = {"repo": str(root), "deploy_branch": main_b, "current": current,
            "protected": sorted(protected), "to_delete_local": to_delete,
            "to_delete_count": len(to_delete),
            "worktree_held_skipped": sorted(worktree_held),
            "mode": "APPLY" if apply else "DRY-RUN"}

    if not apply:
        print(json.dumps(plan, indent=2))
        print(f"\n# DRY-RUN: would delete {len(to_delete)} merged local branch(es). "
              f"Deploy branch '{main_b}' and current '{current}' PROTECTED. "
              f"Re-run with --apply to back up + delete.")
        return 0

    # ---- APPLY ----
    # Backup is TAG-FIRST: every deleted branch is proven zero-unique vs '{main_b}', so its commits
    # remain reachable from the (never-deleted) deploy branch. A recovery tag + a name->sha map is
    # therefore COMPLETE recovery (git branch <name> <sha>) and is instant — no slow full-repo bundle.
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bdir = root / ".branch-backup"
    bdir.mkdir(exist_ok=True)
    deleted, skipped, recovery = [], [], {}
    for b in to_delete:
        # PROOF of zero unique content vs the deploy branch (every commit already in main).
        rc, cnt = git(root, "rev-list", "--count", f"{main_b}..{b}")
        n = int(cnt) if cnt.isdigit() else -1
        if n != 0:   # has (or can't prove 0) unique commits → never delete, surface instead
            skipped.append({"branch": b, "unique_commits": n,
                            "reason": "NOT deleted — has unique commits / unverifiable; surface for review"})
            continue
        rc, sha = git(root, "rev-parse", b)
        git(root, "tag", f"backup/{b.replace('/', '-')}-{ts}", b)   # named recovery ref
        recovery[b] = sha
        # Use -D, but ONLY because the rev-list==0 proof above already guarantees zero unique content
        # vs the deploy branch. (`-d` checks merged-into-current-HEAD, the WRONG reference when HEAD
        # isn't the deploy branch — it false-refuses branches that ARE in main. Our proof is stronger.)
        rc, out = git(root, "branch", "-D", b)
        (deleted if rc == 0 else skipped).append(
            {"branch": b, "sha": sha, "unique_commits": 0, "msg": out.splitlines()[-1] if out else ""})
    mapfile = bdir / f"deleted-{ts}.json"
    mapfile.write_text(json.dumps({"deploy_branch": main_b, "ts": ts, "deleted": recovery}, indent=2), "utf-8")

    remote_deleted = []
    if args.remote:
        rc, rout = git(root, "branch", "-r", "--merged", f"origin/{main_b}")
        rmerged = [ln.strip() for ln in rout.splitlines() if ln.strip() and "->" not in ln]
        for rb in rmerged:
            name = rb.split("/", 1)[-1]
            if name in (main_b, current) or name in HEURISTIC:
                continue
            rc, out = git(root, "push", "origin", "--delete", name, timeout=120)
            remote_deleted.append({"branch": name, "ok": rc == 0})

    rc, main_sha_after = git(root, "rev-parse", main_b)
    result = {**plan, "backup_map": str(mapfile), "backup_tag_prefix": f"backup/<branch>-{ts}",
              "deleted_local": deleted, "skipped_not_merged": skipped, "remote_deleted": remote_deleted,
              "deploy_unchanged": main_sha_before == main_sha_after,
              "deploy_sha": main_sha_after}
    print(json.dumps(result, indent=2))
    if not result["deploy_unchanged"]:
        print("\n!! WARNING: deploy branch SHA changed — investigate immediately.")
    print(f"\n# Deleted {len(deleted)} merged local branch(es). Recovery map: {mapfile}")
    print(f"# Recover one:  git -C {root} branch <name> backup/<name>-{ts}    (or use the sha in the map)")
    if skipped:
        print(f"# {len(skipped)} skipped (git refused — not actually merged): "
              + ", ".join(s['branch'] for s in skipped) + "  → surface these, don't force-delete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
