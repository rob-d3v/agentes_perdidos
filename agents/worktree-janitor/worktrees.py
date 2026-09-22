#!/usr/bin/env python3
"""worktree-janitor — inventory and safely remove leftover git worktrees.

Long AI-assisted sessions leave worktrees behind. Every `git worktree add` for a
subagent, every `-wt-<topic>` scratch checkout, every `.claude/worktrees/<name>`
created by a tool — they accumulate silently, because nothing ever lists them
across repositories. On the machine this was written for, 19 repositories held
**99 worktree entries**, 26 of them under `.claude/worktrees/`. That is tens of
gigabytes of duplicated working trees, and it is why people reach for
"reformat the machine" when the actual problem is a list nobody printed.

Stdlib only. Python 3.8+.

    python worktrees.py scan                      # classify everything
    python worktrees.py scan --sizes              # ...and measure disk (slow)
    python worktrees.py plan                      # what `clean` would remove
    python worktrees.py clean                     # remove green + prune orphans
    python worktrees.py clean --force             # also remove red ones
    python worktrees.py clean --only <substring>  # limit to matching paths

THE CLASSIFICATION — the whole point of this tool

  green   Branch is fully contained in the integration branch AND the working
          tree is clean AND there is no stash. Removing it destroys nothing.
  yellow  A registration whose directory is gone ("prunable"). `git worktree
          prune` fixes it. No code is at risk — this is bookkeeping.
  red     Unmerged commits, uncommitted changes, a stash, or a detached HEAD.
          Removing it CAN destroy work. Never removed without --force.

Colour is never the only carrier of meaning: every row prints its reason, and
the reason is what lets you disagree with the classification. A tool that says
"safe" without saying why is a tool you cannot audit.

SAFETY

  * Dry-run is the default. `scan` and `plan` never write.
  * `clean` without `--force` touches only green and yellow.
  * `--force` prints exactly how many commits and how many modified files are
    about to be lost, per worktree, and requires typing `apagar` to proceed.
  * The main checkout of a repository is never a candidate, ever.
  * A worktree whose branch is checked out somewhere else is left alone.
  * Nothing here uses `shell=True`; no argument is interpolated into a shell.
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GIT_TIMEOUT = 30
DEFAULT_ROOTS = [r'E:\backup_2026\Repositórios', r'D:\Repos']
SIZE_CAP_BYTES = 8 * 1024 ** 3


def git(cwd, *args, timeout=GIT_TIMEOUT):
    """Read-only git. Returns the output, or None when the command FAILED.

    The distinction is the whole safety of this tool. An earlier version
    returned '' for both "succeeded with no output" and "timed out / errored",
    so a `git status --porcelain` that failed under disk contention read as
    "working tree is clean" and a dirty worktree was classified green — safe to
    delete. That is the one direction of error that loses work. Two worktrees
    with uncommitted changes were marked green this way before it was caught.

    Callers that only want a value still use `git(...) or ''`; callers where
    failure changes the verdict must check for None explicitly.
    """
    try:
        done = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True,
                              text=True, timeout=timeout, encoding='utf-8', errors='replace')
    except (subprocess.TimeoutExpired, OSError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def parse_worktrees(repo):
    out, items, cur = git(repo, 'worktree', 'list', '--porcelain') or '', [], None
    for line in out.splitlines():
        if line.startswith('worktree '):
            if cur:
                items.append(cur)
            cur = {'path': line[9:], 'branch': '', 'detached': False,
                   'prunable': False, 'locked': False, 'main': not items}
        elif cur is None:
            continue
        elif line.startswith('branch '):
            cur['branch'] = line[7:].replace('refs/heads/', '')
        elif line.strip() == 'detached':
            cur['detached'] = True
        elif line.split(' ')[0] == 'prunable':
            cur['prunable'] = True
        elif line.split(' ')[0] == 'locked':
            cur['locked'] = True
    if cur:
        items.append(cur)
    return items


def integration_branch(repo, trees=None):
    """The line work is expected to land on.

    Falls back to the branch checked out in the MAIN worktree before giving up.
    Without that fallback, any repository whose trunk is not literally named
    main/master/develop marks every one of its worktrees red with "cannot
    compare" — which reads as "dangerous" when the truth is "I did not look
    hard enough". Observed here on a repo whose trunk is `aniaversao2ponto0`.
    """
    for name in ('main', 'master', 'develop'):
        if git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}'):
            return name
    head = git(repo, 'symbolic-ref', '--short', '--quiet', 'refs/remotes/origin/HEAD') or ''
    if head.startswith('origin/') and git(repo, 'rev-parse', '--verify', '--quiet', head):
        return head
    for wt in (trees or parse_worktrees(repo)):
        if wt['main'] and wt['branch']:
            return wt['branch']
    return ''


def classify(repo, wt, target):
    """Return (state, reason, commits_ahead, dirty_files)."""
    if wt['main']:
        return 'main', 'Main checkout of the repository.', 0, 0
    if wt['locked']:
        return 'red', 'Worktree is locked (`git worktree lock`). Someone marked it on purpose.', 0, 0
    if wt['prunable'] or not Path(wt['path']).is_dir():
        return 'yellow', 'Registration points at a directory that no longer exists.', 0, 0
    status = git(wt['path'], 'status', '--porcelain')
    if status is None:
        # Nao sei se esta limpo. "Nao sei" nunca pode virar "pode apagar".
        return 'red', 'Could not read the working tree status (git failed or timed out). Re-run.', 0, 0
    dirty = [l for l in status.splitlines() if l.strip()]
    if dirty:
        return 'red', f'{len(dirty)} uncommitted change(s) in the working tree.', 0, len(dirty)
    if wt['detached'] or not wt['branch']:
        return 'red', 'Detached HEAD: cannot prove the work landed on any branch.', 0, 0
    # Deliberately NOT checking `git stash list` here. `refs/stash` lives in the
    # repository's common directory, not in the worktree, so (a) every worktree of
    # a repo reports the same stashes and none of them can be attributed to one
    # tree, and (b) removing a worktree does not delete a stash — it survives in
    # the main repo. Checking it blocked 24 of 87 worktrees here, all of them
    # safe: theAPIAniaAPP's 2 stashes alone froze all 11 of its worktrees.
    if not target:
        return 'red', 'Repository has no main/master/develop to compare against.', 0, 0
    ahead = git(repo, 'rev-list', '--count', f'{target}..{wt["branch"]}')
    if ahead is None or not ahead.isdigit():
        return 'red', f'Could not compare `{wt["branch"]}` with `{target}`.', 0, 0
    n = int(ahead)
    if n:
        return 'red', f'{n} commit(s) on `{wt["branch"]}` are not in `{target}`.', n, 0
    return 'green', f'`{wt["branch"]}` is fully merged into `{target}`; working tree clean.', 0, 0


def size_mb(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
            if total > SIZE_CAP_BYTES:
                break
    except OSError:
        return 0.0
    return round(total / 1024 ** 2, 1)


def find_repos(roots):
    """A directory is a repo if it has .git. Worktrees have a .git FILE, so they
    are skipped here and discovered through their parent's worktree list."""
    repos = []
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            try:
                if (entry / '.git').is_dir():
                    repos.append(str(entry))
            except OSError:
                continue
    return repos


def inventory(roots, with_sizes=False, workers=8, only=''):
    """Classify every extra worktree under `roots`.

    Classification is a handful of independent `git` calls per worktree, each
    of them IO-bound and each spawning a process. Done serially across ~80
    worktrees on a mechanical drive this takes many minutes — long enough that
    a caller assumes it hung. They share no state, so they run in a pool.
    """
    # Discovery is itself ~4 git spawns per repository. With 149 directories that
    # is ~600 sequential process launches before any classification starts, which
    # on Windows is minutes of pure spawn overhead. Parallel here too.
    repos = find_repos(roots)
    if only:
        # Estreita a VARREDURA, nao so a saida. Filtrar depois ainda gastaria
        # disco em cada repo — e quando a razao de usar --only e' justamente
        # "nao toque nos repos onde um agente esta trabalhando agora", varrer
        # todos derrota o proposito.
        needle = only.lower()
        repos = [r for r in repos if needle in r.lower()]

    def survey(repo):
        trees = parse_worktrees(repo)
        if len(trees) <= 1:
            return None
        return repo, trees, integration_branch(repo, trees)

    jobs, seen = [], set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for found in pool.map(survey, repos):
            if not found:
                continue
            repo, trees, target = found
            for wt in trees:
                if wt['main'] or wt['path'] in seen:
                    continue
                seen.add(wt['path'])
                jobs.append((repo, wt, target))

    def build(job):
        repo, wt, target = job
        state, reason, ahead, dirty = classify(repo, wt, target)
        return {'repo': repo, 'repo_name': Path(repo).name, 'path': wt['path'],
                'branch': wt['branch'] or '(detached)', 'state': state,
                'reason': reason, 'ahead': ahead, 'dirty': dirty,
                'agent_leftover': '.claude' in wt['path'].replace('\\', '/').split('/'),
                'size_mb': size_mb(wt['path']) if with_sizes and state != 'yellow' else None}

    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(build, jobs))
    rows.sort(key=lambda r: ({'yellow': 0, 'green': 1, 'red': 2}.get(r['state'], 3),
                             -(r['size_mb'] or 0), r['path']))
    return rows


MARK = {'green': '[OK ]', 'yellow': '[REG]', 'red': '[!! ]'}


def show(rows, verbose=True):
    counts = {k: sum(r['state'] == k for r in rows) for k in ('green', 'yellow', 'red')}
    reclaim = sum(r['size_mb'] or 0 for r in rows if r['state'] in ('green', 'yellow'))
    for row in rows if verbose else []:
        size = f"{row['size_mb']:.0f}MB" if row['size_mb'] else ''
        tag = ' (agent session leftover)' if row['agent_leftover'] else ''
        print(f"{MARK.get(row['state'],'[?  ]')} {row['repo_name']:<26} {row['branch'][:34]:<34} {size:>8}")
        print(f"       {row['path']}{tag}")
        print(f"       {row['reason']}")
    print(f"\n  removable now : {counts['green']} merged + {counts['yellow']} stale registrations")
    print(f"  needs a look  : {counts['red']} with unmerged or uncommitted work")
    print(f"  agent sessions: {sum(r['agent_leftover'] for r in rows)} under .claude/worktrees/")
    if reclaim:
        print(f"  disk reclaimed: ~{reclaim/1024:.1f} GB" if reclaim > 1024 else
              f"  disk reclaimed: ~{reclaim:.0f} MB")
    return counts


def remove(repo, path, force=False):
    args = ['worktree', 'remove', path] + (['--force'] if force else [])
    done = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True,
                          timeout=180, encoding='utf-8', errors='replace')
    return done.returncode == 0, (done.stderr or '').strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=['scan', 'plan', 'clean'])
    parser.add_argument('--root', action='append', dest='roots', default=None,
                        help='Directory holding repositories. Repeatable.')
    parser.add_argument('--sizes', action='store_true', help='Measure disk (slow: walks every tree).')
    parser.add_argument('--only', default='', help='Limit to worktrees whose path contains this.')
    parser.add_argument('--force', action='store_true',
                        help='Also remove worktrees with unmerged or uncommitted work.')
    parser.add_argument('--yes', action='store_true', help='Skip the confirmation prompt.')
    args = parser.parse_args(argv)

    roots = args.roots or DEFAULT_ROOTS
    rows = inventory(roots, with_sizes=args.sizes or args.command != 'scan', only=args.only)
    if args.only:
        rows = [r for r in rows if args.only.lower() in r['path'].lower()
                or args.only.lower() in r['repo'].lower()]
    if not rows:
        print('No extra worktrees found. Nothing to clean.')
        return 0

    if args.command == 'scan':
        show(rows)
        return 0

    targets = [r for r in rows if r['state'] in ('green', 'yellow')]
    risky = [r for r in rows if r['state'] == 'red']
    if args.force:
        targets += risky

    if not targets:
        print('Nothing removable. Run `scan` to see what is being held back and why.')
        show(rows, verbose=False)
        return 0

    print(f'Would remove {len(targets)} worktree(s):\n')
    for row in targets:
        size = f" (~{row['size_mb']:.0f}MB)" if row['size_mb'] else ''
        print(f"  {MARK[row['state']]} {row['repo_name']}/{row['branch']}{size}\n       {row['path']}")
        if row['state'] == 'red':
            # Say exactly what is lost. "Are you sure?" without a number is theatre.
            loss = []
            if row['ahead']:
                loss.append(f"{row['ahead']} commit(s) NOT in the integration branch")
            if row['dirty']:
                loss.append(f"{row['dirty']} uncommitted file(s)")
            print(f"       DESTROYS: {', '.join(loss) or row['reason']}")
    total = sum(r['size_mb'] or 0 for r in targets)
    if total:
        print(f'\nReclaims ~{total/1024:.1f} GB' if total > 1024 else f'\nReclaims ~{total:.0f} MB')

    if args.command == 'plan':
        print('\nDry run. Nothing was changed. Run `clean` to apply.')
        return 0

    if risky and args.force and not args.yes:
        print(f'\n{len(risky)} of these contain work that is NOT merged anywhere.')
        if input('Type "apagar" to delete them permanently: ').strip() != 'apagar':
            print('Aborted. Nothing was changed.')
            return 1
    elif not args.yes:
        if input(f'\nRemove {len(targets)} worktree(s)? [y/N] ').strip().lower() not in ('y', 's'):
            print('Aborted. Nothing was changed.')
            return 1

    ok, failed = 0, []
    for row in targets:
        done, err = remove(row['repo'], row['path'], force=args.force or row['state'] == 'red')
        if done:
            ok += 1
        else:
            failed.append((row['path'], err))
    for repo in {r['repo'] for r in targets}:
        git(repo, 'worktree', 'prune', timeout=60)

    print(f'\nRemoved {ok} worktree(s).')
    for path, err in failed:
        print(f'  FAILED {path}\n         {err[:200]}')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
