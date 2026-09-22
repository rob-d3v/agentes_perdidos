#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
diskaudit.py — the disk-audit agent's hands.

Finds out what is eating a Windows disk and says what can be reclaimed, ranked by
risk. Read-only by default: `scan` NEVER deletes anything. Deletion lives in a
separate `clean` subcommand that only accepts SAFE findings from a report you have
already read, and demands a typed confirmation.

    diskaudit.py scan    ROOT [ROOT...]     # the audit (largest dirs + junk + risk)
    diskaudit.py caches                     # package-manager / app caches (fast probe)
    diskaudit.py windows                    # Windows junk, WSL/Docker vhdx, pagefile
    diskaudit.py repos   ROOT               # .git bloat ranking across a repo forest
    diskaudit.py dupes   ROOT [ROOT...]     # exact duplicates (size-group then hash)
    diskaudit.py clean   --from report.json --category node_modules \\
                         --yes-delete-for-real

Stdlib only — runs with plain `python` or `uv run`, online or offline, on Windows
(PowerShell or Git Bash) and on POSIX.

Windows correctness (see SKILL.md "Gotchas"):
  * junctions / symlinks are NEVER followed  (AppData is full of them -> infinite
    loops + double counting);
  * paths are opened through the `\\\\?\\` long-path prefix so >260-char
    node_modules trees are sized instead of erroring;
  * PermissionError / files-in-use are counted and reported, never fatal;
  * pagefile.sys / hiberfil.sys / swapfile.sys / System Volume Information are
    reported for size only and can never be proposed for deletion.

Read SKILL.md first for the risk matrix and the deletion policy.
"""
from __future__ import annotations

import argparse
import ctypes
import fnmatch
import hashlib
import json
import os
import shutil
import stat as statmod
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

IS_WIN = os.name == "nt"
SCHEMA = "disk-audit/1"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Risk levels. The whole point of the agent: nothing outside SAFE is ever a
# deletion candidate, and NEVER is structurally undeletable by `clean`.
# ---------------------------------------------------------------------------
SAFE = "SAFE"       # regenerable by a command; delete without thinking
REVIEW = "REVIEW"   # almost certainly junk, but confirm first
NEVER = "NEVER"     # system / user data. Reported for size only.
RISK_ORDER = {SAFE: 0, REVIEW: 1, NEVER: 2}


# ---------------------------------------------------------------------------
# Sizes, paths, long-path prefix
# ---------------------------------------------------------------------------
def human(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0 or unit == "PB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def parse_size(s: str) -> int:
    s = str(s).strip().upper().replace(" ", "")
    mult = 1
    for suf, m in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10),
                   ("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10), ("B", 1)):
        if s.endswith(suf):
            s, mult = s[: -len(suf)], m
            break
    return int(float(s or 0) * mult)


def long_path(p: str) -> str:
    """Prefix with \\\\?\\ so Windows APIs accept >260-char paths."""
    if not IS_WIN:
        return p
    if p.startswith("\\\\?\\"):
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\"):                      # UNC \\server\share
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def display(p: str) -> str:
    """Strip the long-path prefix for human output / JSON."""
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(display(p)))


_CLUSTER_CACHE: dict[str, int] = {}


def cluster_size(path: str) -> int:
    """Bytes per allocation unit of the volume holding `path` (4096 fallback)."""
    drive = os.path.splitdrive(os.path.abspath(display(path)))[0] or "C:"
    drive = drive.upper() + "\\"
    if drive in _CLUSTER_CACHE:
        return _CLUSTER_CACHE[drive]
    size = 4096
    if IS_WIN:
        try:
            spc = ctypes.c_ulong()
            bps = ctypes.c_ulong()
            free = ctypes.c_ulong()
            total = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetDiskFreeSpaceW(
                ctypes.c_wchar_p(drive), ctypes.byref(spc), ctypes.byref(bps),
                ctypes.byref(free), ctypes.byref(total))
            if ok and spc.value and bps.value:
                size = spc.value * bps.value
        except Exception:
            pass
    _CLUSTER_CACHE[drive] = size
    return size


# Windows file attributes we care about.
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003   # junction
IO_REPARSE_TAG_SYMLINK = 0xA000000C


def is_reparse(st) -> bool:
    """True for junctions, symlinks and cloud placeholders.

    We never follow these. On Windows a junction under AppData (e.g.
    `Application Data` -> `AppData\\Local`) makes a naive walker loop forever and
    count the same bytes many times.
    """
    attrs = getattr(st, "st_file_attributes", None)
    if attrs is not None:
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    return statmod.S_ISLNK(st.st_mode)


def reparse_kind(st) -> str:
    tag = getattr(st, "st_reparse_tag", 0)
    if tag == IO_REPARSE_TAG_MOUNT_POINT:
        return "junction"
    if tag == IO_REPARSE_TAG_SYMLINK:
        return "symlink"
    return f"reparse:{tag:#x}" if tag else "link"


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------
@dataclass
class Rule:
    category: str
    names: set[str]
    risk: str
    note: str
    action: str
    marker: tuple[str, ...] = ()        # PARENT must contain one of these to match
    self_marker: tuple[str, ...] = ()   # the dir ITSELF must contain one of these


REPO_MARKERS = ("package.json", "pyproject.toml", "Cargo.toml", "pom.xml", "go.mod",
                "build.gradle", "build.gradle.kts", "CMakeLists.txt", "tsconfig.json",
                "composer.json", ".git", "Makefile", "index.html", "requirements.txt")

DIR_RULES: list[Rule] = [
    Rule("node_modules", {"node_modules"}, SAFE,
         "regenerable from the lockfile", "delete; `npm i` / `pnpm i` restores it"),
    Rule("python_cache", {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                          ".tox", ".ipynb_checkpoints", ".cache"}, SAFE,
         "interpreter / tool cache, rebuilt on demand", "delete"),
    Rule("build_cache", {".next", ".nuxt", ".turbo", ".parcel-cache", ".svelte-kit",
                         ".angular", ".dart_tool", ".expo", ".vite", ".output",
                         ".nyc_output", "coverage", ".gradle"}, SAFE,
         "framework/build tool cache, rebuilt by the next build", "delete"),
    Rule("build_output", {"dist", "build", "out", "webbuild", "release", "target"}, REVIEW,
         "build artifact; only junk if you can rebuild it", "delete after confirming a rebuild works",
         marker=REPO_MARKERS),
    Rule("dotnet_output", {"bin", "obj"}, REVIEW,
         ".NET build output", "delete; `dotnet build` restores it",
         marker=("*.csproj", "*.sln", "*.vbproj", "*.fsproj")),
    # pyvenv.cfg lives INSIDE the venv, not next to it -> self_marker, not marker.
    Rule("python_env", {".venv", "venv", "virtualenv", "env"}, REVIEW,
         "virtualenv; regenerable but needs a reinstall (offline = broken)",
         "delete; `uv sync` / `pip install -r requirements.txt` restores it",
         self_marker=("pyvenv.cfg",)),
    Rule("android_build", {".cxx", ".externalNativeBuild"}, SAFE,
         "Android/NDK intermediate build dir", "delete"),
]

# Absolute paths (lower-cased, no trailing sep) that classify on exact match or
# prefix. Filled by build_known_paths() so it works for any user profile.
KNOWN: dict[str, tuple[str, str, str, str]] = {}
KNOWN_DISPLAY: dict[str, str] = {}   # normcase key -> original-case path


def _reg(path: str, category: str, risk: str, note: str, action: str) -> None:
    if not path:
        return
    real = os.path.abspath(os.path.expanduser(path))
    key = os.path.normcase(real)
    KNOWN[key] = (category, risk, note, action)
    KNOWN_DISPLAY.setdefault(key, real)


def build_known_paths() -> None:
    if KNOWN:
        return
    home = os.path.expanduser("~")
    lad = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    rad = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    win = os.environ.get("SystemRoot", r"C:\Windows")
    sysdrive = os.environ.get("SystemDrive", "C:")
    pdata = os.environ.get("ProgramData", r"C:\ProgramData")

    # --- package manager caches: always re-downloadable -------------------
    pkg = [
        (os.path.join(lad, "npm-cache"), "npm cache", "npm cache clean --force"),
        (os.path.join(rad, "npm-cache"), "npm cache", "npm cache clean --force"),
        (os.path.join(lad, "pnpm-store"), "pnpm content-addressable store", "pnpm store prune"),
        (os.path.join(lad, "pnpm", "store"), "pnpm store", "pnpm store prune"),
        (os.path.join(lad, "Yarn", "Cache"), "yarn cache", "yarn cache clean"),
        (os.path.join(lad, "pip", "Cache"), "pip wheel cache", "pip cache purge"),
        (os.path.join(lad, "uv", "cache"), "uv cache", "uv cache clean"),
        (os.path.join(home, ".cargo", "registry"), "cargo crate registry", "cargo cache; re-fetched on build"),
        (os.path.join(home, ".cargo", "git"), "cargo git checkouts", "re-fetched on build"),
        (os.path.join(home, ".gradle", "caches"), "gradle cache", "re-downloaded on build"),
        (os.path.join(home, ".m2", "repository"), "maven local repo", "re-downloaded on build"),
        (os.path.join(home, ".nuget", "packages"), "nuget global packages", "dotnet nuget locals all --clear"),
        (os.path.join(lad, "NuGet", "v3-cache"), "nuget http cache", "dotnet nuget locals all --clear"),
        (os.path.join(home, "go", "pkg", "mod"), "go module cache", "go clean -modcache"),
        (os.path.join(lad, "Microsoft", "vscode-cpptools"), "vscode C++ IntelliSense cache", "delete"),
        (os.path.join(lad, "Google", "Chrome", "User Data", "Default", "Cache"), "chrome cache", "delete"),
        (os.path.join(lad, "Microsoft", "Edge", "User Data", "Default", "Cache"), "edge cache", "delete"),
        (os.path.join(lad, "Puppeteer"), "puppeteer chromium downloads", "delete unused revisions"),
        (os.path.join(lad, "ms-playwright"), "playwright browser downloads", "npx playwright uninstall --all"),
        (os.path.join(lad, "electron"), "electron download cache", "delete"),
        (os.path.join(lad, "electron-builder", "Cache"), "electron-builder cache", "delete"),
    ]
    for p, note, action in pkg:
        _reg(p, "pkg_cache", SAFE, note, action)

    # NOT pkg_cache on purpose: `temp_dir` and `ide_cache` are outside
    # DELETABLE_CATEGORIES, so `clean` can never rmtree them. %TEMP% holds live
    # files of every running process (and this tool's own scratch), and
    # LocalAppData\JetBrains mixes caches with the Toolbox installation.
    _reg(os.path.join(lad, "Temp"), "temp_dir", REVIEW,
         "user temp dir — running processes hold files open here",
         "Settings > System > Storage > Temporary files, or delete what is unlocked")
    _reg(os.path.join(os.environ.get("TEMP", os.path.join(lad, "Temp"))), "temp_dir", REVIEW,
         "%TEMP%", "Storage Sense / Disk Cleanup")
    _reg(os.path.join(lad, "JetBrains"), "ide_cache", REVIEW,
         "JetBrains caches/logs/indexes — also holds the Toolbox install",
         "delete only the per-IDE cache/log/index subfolders")
    _reg(os.path.join(lad, "CrashDumps"), "windows_junk", REVIEW,
         "application crash dumps", "delete")

    # --- virtual disks: huge, grow-only, NEVER delete blind ----------------
    _reg(os.path.join(lad, "Docker", "wsl"), "docker_wsl", REVIEW,
         "Docker Desktop WSL data (ext4.vhdx). Grows, never shrinks by itself",
         "do NOT delete: `docker system prune -a --volumes` then compact the vhdx")
    _reg(os.path.join(lad, "Packages"), "appx_packages", REVIEW,
         "Store/WSL app data. WSL distro .vhdx files live here",
         "inspect per-package; compact vhdx instead of deleting")
    _reg(os.path.join(pdata, "DockerDesktop"), "docker_wsl", REVIEW,
         "Docker Desktop shared data", "prune from Docker Desktop, then compact")

    # --- Windows junk ------------------------------------------------------
    _reg(os.path.join(win, "Temp"), "windows_junk", REVIEW,
         "system temp; some files are locked by running services", "delete the unlocked files")
    _reg(os.path.join(win, "SoftwareDistribution", "Download"), "windows_junk", REVIEW,
         "Windows Update download staging",
         "net stop wuauserv && empty the folder && net start wuauserv")
    _reg(os.path.join(win, "Prefetch"), "windows_junk", NEVER,
         "boot/app prefetch: deleting it just slows the machine down", "leave it alone")
    _reg(os.path.join(win, "Installer"), "windows_junk", NEVER,
         "MSI cache required to repair/uninstall installed software",
         "never delete; only PatchCleaner-style tools may prune orphans")
    _reg(os.path.join(win, "WinSxS"), "windows_junk", NEVER,
         "component store; deleting breaks Windows Update",
         "DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase")
    _reg(os.path.join(win, "Minidump"), "windows_junk", REVIEW, "kernel minidumps", "delete")
    _reg(os.path.join(win, "LiveKernelReports"), "windows_junk", REVIEW,
         "live kernel dumps", "delete")
    _reg(os.path.join(pdata, "Microsoft", "Windows", "WER"), "windows_junk", REVIEW,
         "Windows Error Reporting queue", "delete")
    _reg(os.path.join(pdata, "Microsoft", "Windows", "DeliveryOptimization"), "windows_junk", REVIEW,
         "Delivery Optimization P2P update cache", "Settings > System > Storage > Temporary files")
    _reg(sysdrive + "\\Windows.old", "windows_junk", REVIEW,
         "previous Windows install; blocks rollback once removed",
         "use Disk Cleanup > 'Previous Windows installation(s)', not rm")
    _reg(sysdrive + "\\$WinREAgent", "windows_junk", REVIEW,
         "leftover of a feature update", "Disk Cleanup")
    _reg(sysdrive + "\\$Windows.~BT", "windows_junk", REVIEW,
         "upgrade staging leftovers", "Disk Cleanup")
    _reg(sysdrive + "\\$Windows.~WS", "windows_junk", REVIEW,
         "upgrade staging leftovers", "Disk Cleanup")


# Files at a volume root that are pure system state: size-report only.
SYSTEM_FILES = {
    "pagefile.sys": ("virtual memory swap file",
                     "shrink via System Properties > Advanced > Performance > Virtual memory"),
    "swapfile.sys": ("Store-app swap file", "managed with the pagefile"),
    "hiberfil.sys": ("hibernation image (~40% of RAM)",
                     "reclaim with `powercfg /h off` (loses hibernate + fast startup)"),
    "dumpstack.log.tmp": ("crash-dump stack log", "recreated at boot"),
    "memory.dmp": ("full kernel memory dump", "safe to remove via Disk Cleanup"),
}

# Directories never entered / never proposed. Reported for size only.
NEVER_NAMES = {"system volume information", "$recycle.bin", "$sysreset", "recovery",
               "boot", "efi", "config.msi", "perflogs"}

BIG_EXT = {".apk", ".aab", ".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".zip", ".7z",
           ".rar", ".gz", ".tgz", ".bz2", ".xz", ".tar", ".bak", ".old", ".sql",
           ".dump", ".dmp", ".msi", ".exe", ".pkg", ".dmg", ".mp4", ".mkv", ".mov",
           ".psd", ".ai", ".pdb", ".jar", ".war", ".aar", ".log"}


def _parent_has(parent: str, markers: tuple[str, ...]) -> bool:
    for m in markers:
        if "*" in m:
            try:
                with os.scandir(parent) as it:
                    for e in it:
                        if fnmatch.fnmatch(e.name.lower(), m.lower()):
                            return True
            except OSError:
                return False
        elif os.path.exists(os.path.join(parent, m)):
            return True
    return False


def classify_dir(name: str, path: str, parent: str) -> tuple[str, str, str, str] | None:
    """-> (category, risk, note, action) or None."""
    build_known_paths()
    hit = KNOWN.get(norm(path))
    if hit:
        return hit
    low = name.lower()
    if low in NEVER_NAMES:
        return ("system", NEVER, "Windows-managed volume metadata", "never touch")
    for rule in DIR_RULES:
        if low in rule.names:
            if rule.marker and not _parent_has(parent, rule.marker):
                continue
            if rule.self_marker and not _parent_has(path, rule.self_marker):
                continue
            return (rule.category, rule.risk, rule.note, rule.action)
    return None


def shorten(s: str, n: int) -> str:
    """Truncate keeping the TAIL — the informative half of a long Windows path."""
    s = str(s)
    return s if len(s) <= n else "..." + s[-(n - 3):]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    path: str
    category: str
    risk: str
    bytes: int
    files: int
    note: str
    action: str


@dataclass
class RepoInfo:
    path: str
    total_bytes: int
    git_bytes: int
    worktree_bytes: int
    ratio: float
    loose_objects: int = 0
    size_loose: str = ""
    size_pack: str = ""
    packs: int = 0
    verdict: str = ""


@dataclass
class Options:
    depth: int = 3
    top: int = 25
    min_size: int = 100 * (1 << 20)
    large_file: int = 500 * (1 << 20)
    dupes: bool = False
    dupe_min: int = 1 << 20
    on_disk: bool = False
    git: bool = True
    exclude: list[str] = field(default_factory=list)
    quiet: bool = False
    vhdx: bool = False       # probe AppData for WSL/Docker virtual disks


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class Scanner:
    def __init__(self, opts: Options):
        self.o = opts
        self.dirs: list[tuple[str, int]] = []
        self.findings: list[Finding] = []
        self.large_files: list[dict] = []
        self.system_files: list[dict] = []
        self.repos: list[RepoInfo] = []
        self.by_size: dict[int, list[str]] = defaultdict(list)
        self.errors: list[dict] = []
        self.links_skipped = 0
        self.n_dirs = 0
        self.n_files = 0
        self.total_bytes = 0
        self._t0 = time.time()
        self._claimed: set[str] = set()

    # -- helpers ----------------------------------------------------------
    def _fsize(self, st, path: str) -> int:
        if not self.o.on_disk:
            return st.st_size
        cs = cluster_size(path)
        return ((st.st_size + cs - 1) // cs) * cs if st.st_size else 0

    def _excluded(self, path: str) -> bool:
        if not self.o.exclude:
            return False
        low = norm(path)
        return any(fnmatch.fnmatch(low, os.path.normcase(pat)) for pat in self.o.exclude)

    def _tick(self) -> None:
        if self.o.quiet:
            return
        if self.n_dirs % 4000 == 0:
            el = time.time() - self._t0
            sys.stderr.write(
                f"\r  scanning… {self.n_dirs:,} dirs / {self.n_files:,} files / "
                f"{human(self.total_bytes)} / {el:,.0f}s")
            sys.stderr.flush()

    # -- the walk ---------------------------------------------------------
    def walk(self, root: str) -> int:
        root_lp = long_path(root)
        total, _ = self._walk(root_lp, 0, junk=None, root=root_lp)
        self.dirs.append((display(root_lp), total))
        if not self.o.quiet:
            sys.stderr.write("\r" + " " * 78 + "\r")
            sys.stderr.flush()
        return total

    def _walk(self, path: str, depth: int, junk: str | None, root: str) -> tuple[int, int]:
        """Return (bytes, files) for the subtree. Iterative-safe recursion.

        `junk` is the category of the nearest enclosing junk dir, so we never
        emit a nested finding (a __pycache__ inside node_modules is already
        counted by the node_modules finding).
        """
        self.n_dirs += 1
        self._tick()
        total = 0
        nfiles = 0
        subdirs: list[tuple[str, str]] = []
        try:
            it = os.scandir(path)
        except PermissionError as e:
            self.errors.append({"path": display(path), "error": "permission denied",
                                "detail": str(e.strerror or e)})
            return 0, 0
        except OSError as e:
            self.errors.append({"path": display(path), "error": "unreadable",
                                "detail": str(e.strerror or e)})
            return 0, 0
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as e:                       # dir vanished mid-scan
                    self.errors.append({"path": display(path), "error": "iteration failed",
                                        "detail": str(e)})
                    break
                try:
                    st = entry.stat(follow_symlinks=False)  # cached by scandir on Windows
                except OSError as e:
                    self.errors.append({"path": display(entry.path), "error": "stat failed",
                                        "detail": str(getattr(e, "strerror", e))})
                    continue
                if is_reparse(st):
                    # Junctions/symlinks: do not follow, do not count. This is the
                    # single most important rule for a Windows scanner.
                    self.links_skipped += 1
                    continue
                try:
                    isdir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if isdir:
                    subdirs.append((entry.name, entry.path))
                    continue
                # --- a regular file ---
                sz = self._fsize(st, entry.path)
                total += sz
                nfiles += 1
                self.n_files += 1
                self.total_bytes += sz
                low = entry.name.lower()
                if low in SYSTEM_FILES and depth == 0:
                    note, action = SYSTEM_FILES[low]
                    self.system_files.append({"path": display(entry.path), "bytes": sz,
                                              "note": note, "action": action, "risk": NEVER})
                    continue
                if junk is None and sz >= self.o.large_file:
                    self.large_files.append({
                        "path": display(entry.path), "bytes": sz,
                        "ext": os.path.splitext(low)[1],
                        "mtime": _iso(st.st_mtime),
                        "risk": REVIEW,
                        "note": "large loose file",
                        "action": "check if it is a build artifact / old backup, then delete",
                    })
                if self.o.dupes and junk is None and sz >= self.o.dupe_min:
                    self.by_size[st.st_size].append(entry.path)

        saw_git = False
        git_bytes = 0
        for name, child in subdirs:
            if self._excluded(child):
                continue
            cat = None
            if junk is None:
                cat = classify_dir(name, child, path)
            is_git = name.lower() == ".git"
            if cat and cat[1] == NEVER and cat[0] == "system":
                # do not descend into volume metadata; report 0 (unreadable anyway)
                self.findings.append(Finding(display(child), cat[0], NEVER, 0, 0,
                                             cat[2], cat[3]))
                continue
            sub, subf = self._walk(child, depth + 1, junk or (cat[0] if cat else None), root)
            total += sub
            nfiles += subf
            if is_git:
                saw_git = True
                git_bytes = sub
            if cat and sub > 0:
                key = norm(child)
                if key not in self._claimed:
                    self._claimed.add(key)
                    self.findings.append(Finding(display(child), cat[0], cat[1], sub,
                                                 subf, cat[2], cat[3]))
            if depth + 1 <= self.o.depth:
                self.dirs.append((display(child), sub))

        if saw_git:
            work = max(total - git_bytes, 0)
            ratio = (git_bytes / work) if work else float("inf")
            self.repos.append(RepoInfo(display(path), total, git_bytes, work, round(ratio, 2)))
        return total, nfiles

    # -- post passes ------------------------------------------------------
    def find_dupes(self) -> list[dict]:
        """Exact duplicates: group by size first, hash ONLY inside collisions."""
        groups = [(sz, ps) for sz, ps in self.by_size.items() if len(ps) > 1 and sz > 0]
        groups.sort(key=lambda g: g[0] * (len(g[1]) - 1), reverse=True)
        out: list[dict] = []
        for sz, paths in groups:
            # cheap pre-filter: first 64 KiB only
            head: dict[str, list[str]] = defaultdict(list)
            for p in paths:
                h = _hash_file(p, limit=65536)
                if h:
                    head[h].append(p)
            for _, cand in head.items():
                if len(cand) < 2:
                    continue
                full: dict[str, list[str]] = defaultdict(list)
                for p in cand:
                    h = _hash_file(p)
                    if h:
                        full[h].append(p)
                for h, same in full.items():
                    if len(same) < 2:
                        continue
                    out.append({
                        "sha256": h, "bytes_each": sz, "copies": len(same),
                        "reclaimable": sz * (len(same) - 1),
                        "paths": [display(p) for p in same],
                        "risk": REVIEW,
                        "note": "byte-identical copies",
                        "action": "keep one, delete the rest (verify nothing links to them)",
                    })
        out.sort(key=lambda d: d["reclaimable"], reverse=True)
        return out

    def probe_git(self) -> None:
        """`git count-objects -vH` on repos whose .git looks disproportionate."""
        if not self.repos or not self.o.git or not shutil.which("git"):
            return
        for r in self.repos:
            big = r.git_bytes >= 200 * (1 << 20)
            lopsided = r.worktree_bytes and r.git_bytes > 2 * r.worktree_bytes and r.git_bytes > 50 * (1 << 20)
            if not (big or lopsided):
                r.verdict = "ok"
                continue
            info = _git_count_objects(r.path)
            r.loose_objects = info.get("count", 0)
            r.size_loose = info.get("size", "")
            r.size_pack = info.get("size-pack", "")
            r.packs = info.get("packs", 0)
            r.verdict = "bloated — run `git gc --aggressive --prune=now`"
            self.findings.append(Finding(
                os.path.join(r.path, ".git"), "git_bloat", REVIEW, r.git_bytes, 0,
                f".git is {r.ratio}x the working tree ({human(r.worktree_bytes)}); "
                f"{r.loose_objects:,} loose objects, {r.packs} packs",
                "cd repo && git gc --aggressive --prune=now  (NEVER delete .git)"))


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return ""


def _hash_file(path: str, limit: int | None = None) -> str | None:
    h = hashlib.sha256()
    read = 0
    try:
        with open(long_path(path), "rb", buffering=0) as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
                if limit and read >= limit:
                    break
    except OSError:
        return None
    return h.hexdigest()


def _git_count_objects(repo: str) -> dict:
    try:
        out = subprocess.run(["git", "-C", display(repo), "count-objects", "-vH"],
                             capture_output=True, text=True, timeout=120)
    except Exception:
        return {}
    d: dict = {}
    for line in (out.stdout or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        d[k.strip()] = int(v) if v.isdigit() else v
    return d


# ---------------------------------------------------------------------------
# Fast standalone sizing (used by `caches` / `windows`)
# ---------------------------------------------------------------------------
def dir_size(path: str, on_disk: bool = False) -> tuple[int, int]:
    total = 0
    files = 0
    stack = [long_path(path)]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                    if is_reparse(st):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        if on_disk:
                            cs = cluster_size(entry.path)
                            total += ((st.st_size + cs - 1) // cs) * cs if st.st_size else 0
                        else:
                            total += st.st_size
                        files += 1
                except OSError:
                    continue
    return total, files


def find_vhdx(on_disk: bool = False) -> list[dict]:
    """Locate WSL / Docker / Hyper-V virtual disks (grow-only, never auto-shrink)."""
    out: list[dict] = []
    home = os.path.expanduser("~")
    lad = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    roots = [os.path.join(lad, "Packages"), os.path.join(lad, "Docker"),
             os.path.join(lad, "wsl"), r"C:\ProgramData\Microsoft\Windows\Virtual Hard Disks"]
    for root in roots:
        if not os.path.isdir(root):
            continue
        stack = [long_path(root)]
        while stack:
            cur = stack.pop()
            try:
                it = os.scandir(cur)
            except OSError:
                continue
            with it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if is_reparse(st):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.name.lower().endswith((".vhdx", ".vhd")):
                            out.append({
                                "path": display(entry.path), "bytes": st.st_size,
                                "category": "docker_wsl", "risk": REVIEW,
                                "note": "virtual disk — grows forever, never shrinks itself; "
                                        "deleting it destroys the distro/containers inside",
                                "action": "wsl --shutdown; then `wsl --manage <distro> --set-sparse true` "
                                          "or Optimize-VHD / diskpart `compact vdisk`",
                                "mtime": _iso(st.st_mtime),
                            })
                    except OSError:
                        continue
    out.sort(key=lambda d: d["bytes"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Deletion guard rails
# ---------------------------------------------------------------------------
DELETABLE_CATEGORIES = {"node_modules", "python_cache", "build_cache", "pkg_cache",
                        "android_build"}

PROTECTED_BASENAMES = {".git", ".github", "src", "source", "srcs", "app", "lib", "assets",
                       "public", "static", "data", "db", "database", "docs", "raw", "wiki",
                       "documents", "desktop", "downloads", "pictures", "videos", "music",
                       "onedrive", "appdata", "users", "windows", "system32", "syswow64",
                       "program files", "program files (x86)", "programdata", "backup",
                       "backups", "repositorios", "repositórios", ".ssh", ".gnupg", ".aws",
                       ".config", ".obsidian"}


def protected_prefixes() -> list[str]:
    home = os.path.expanduser("~")
    ps = [os.environ.get("SystemRoot", r"C:\Windows"),
          os.environ.get("ProgramFiles", r"C:\Program Files"),
          os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
          os.path.join(home, "Downloads"), os.path.join(home, "Pictures"),
          os.path.join(home, "Videos"), os.path.join(home, "Music"),
          os.path.join(home, "OneDrive"), os.path.join(home, ".ssh"),
          os.path.join(home, ".gnupg"), os.path.join(home, ".aws")]
    return [os.path.normcase(os.path.abspath(p)) for p in ps if p]


def is_protected(path: str) -> str | None:
    """Return a reason string if `path` must never be deleted, else None."""
    q = norm(path)
    drive, rest = os.path.splitdrive(q)
    parts = [p for p in rest.split(os.sep) if p]
    if len(parts) < 2:
        return "too close to the volume root"
    base = parts[-1]
    if base in PROTECTED_BASENAMES:
        return f"'{base}' is a protected directory name"
    for p in parts:
        if p in NEVER_NAMES or p.startswith("$"):
            return f"path crosses system metadata ('{p}')"
    for pref in protected_prefixes():
        if q == pref or q.startswith(pref + os.sep):
            # AppData caches are the deliberate exception, handled by KNOWN
            return f"inside protected location {pref}"
    if os.path.isdir(os.path.join(display(path), ".git")):
        return "contains a .git repository"
    return None


# --- Recycle Bin via SHFileOperationW (ctypes, stdlib) ---------------------
FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_NOCONFIRMMKDIR = 0x0200


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def recycle(paths: list[str]) -> tuple[bool, str]:
    """Send paths to the Recycle Bin. Returns (ok, message).

    Caveats that MUST be surfaced to the user (see SKILL.md):
      * SHFileOperationW does not understand the \\\\?\\ prefix and is MAX_PATH
        bound — deep node_modules trees can fail with 0x7C/0x402;
      * an item larger than the bin quota is deleted PERMANENTLY, silently,
        because we pass FOF_NOCONFIRMATION.
    """
    if not IS_WIN:
        return False, "Recycle Bin is Windows-only"
    clean = []
    for p in paths:
        ap = os.path.abspath(display(p))
        if len(ap) >= 250:
            return False, f"path too long for the shell API ({len(ap)} chars): {ap}"
        clean.append(ap)
    buf = "\0".join(clean) + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_NOCONFIRMMKDIR
    op.fAnyOperationsAborted = 0
    op.hNameMappings = None
    op.lpszProgressTitle = None
    try:
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:                                    # pragma: no cover
        return False, f"SHFileOperationW unavailable: {e}"
    if rc != 0:
        return False, f"SHFileOperationW failed with code {rc:#x}"
    if op.fAnyOperationsAborted:
        return False, "operation aborted by the shell"
    return True, "sent to Recycle Bin"


def _force_rm(func, path, exc):
    """rmtree onerror: git objects are read-only on Windows."""
    try:
        os.chmod(path, statmod.S_IWRITE)
        func(path)
    except Exception:
        raise


def permanent_delete(path: str) -> tuple[bool, str]:
    try:
        p = long_path(path)
        if os.path.isdir(p):
            try:
                shutil.rmtree(p, onexc=lambda f, pa, e: _force_rm(f, pa, e))
            except TypeError:                                  # py<3.12
                shutil.rmtree(p, onerror=_force_rm)
        else:
            os.chmod(p, statmod.S_IWRITE)
            os.remove(p)
        return True, "deleted permanently"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _table(rows: list[list[str]], headers: list[str], aligns: str = "") -> str:
    if not rows:
        return "  (nothing)\n"
    cols = len(headers)
    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(r[i])))
    aligns = (aligns + "l" * cols)[:cols]

    def fmt(vals):
        out = []
        for i, v in enumerate(vals):
            v = str(v)
            out.append(v.rjust(widths[i]) if aligns[i] == "r" else v.ljust(widths[i]))
        return "  " + "  ".join(out).rstrip()

    lines = [fmt(headers), "  " + "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines) + "\n"


def _covered_by(path: str, parents: list[str]) -> bool:
    """True if `path` already lives inside one of `parents` (normcased)."""
    q = norm(path)
    return any(q == p or q.startswith(p + os.sep) for p in parents)


def build_report(roots: list[str], sc: Scanner, dupes: list[dict], opts: Options) -> dict:
    by_cat: dict[str, dict] = {}
    for f in sc.findings:
        c = by_cat.setdefault(f.category, {"category": f.category, "risk": f.risk,
                                           "count": 0, "bytes": 0, "action": f.action,
                                           "note": f.note})
        c["count"] += 1
        c["bytes"] += f.bytes
        if RISK_ORDER[f.risk] > RISK_ORDER[c["risk"]]:
            c["risk"] = f.risk
    # Virtual disks live under the user profile. Only probe when that is in
    # scope, otherwise a 5 MB scan would report 100 GB of unrelated Docker data.
    vh = find_vhdx(opts.on_disk) if (IS_WIN and opts.vhdx) else []
    # A .vhdx usually sits INSIDE a directory that is already a finding
    # (AppData\Local\Docker\wsl). Counting both would double the total.
    claimed = [norm(f.path) for f in sc.findings]
    for v in vh:
        if _covered_by(v["path"], claimed):
            continue
        c = by_cat.setdefault("docker_wsl", {"category": "docker_wsl", "risk": REVIEW,
                                             "count": 0, "bytes": 0,
                                             "action": v["action"], "note": v["note"]})
        c["count"] += 1
        c["bytes"] += v["bytes"]
    if dupes:
        by_cat["duplicates"] = {"category": "duplicates", "risk": REVIEW,
                                "count": sum(d["copies"] - 1 for d in dupes),
                                "bytes": sum(d["reclaimable"] for d in dupes),
                                "action": "keep one copy of each",
                                "note": "byte-identical files"}
    if sc.large_files:
        by_cat["large_files"] = {"category": "large_files", "risk": REVIEW,
                                 "count": len(sc.large_files),
                                 "bytes": sum(f["bytes"] for f in sc.large_files),
                                 "action": "triage individually",
                                 "note": f"loose files >= {human(opts.large_file)}"}
    if sc.system_files:
        by_cat["system_files"] = {"category": "system_files", "risk": NEVER,
                                  "count": len(sc.system_files),
                                  "bytes": sum(f["bytes"] for f in sc.system_files),
                                  "action": "reconfigure Windows, never delete",
                                  "note": "pagefile / hiberfil / dumps"}

    drives = []
    seen = set()
    for r in roots:
        d = os.path.splitdrive(os.path.abspath(r))[0] or r
        if d in seen:
            continue
        seen.add(d)
        try:
            u = shutil.disk_usage(os.path.abspath(r))
            drives.append({"drive": d or r, "total": u.total, "used": u.used,
                           "free": u.free, "used_pct": round(100 * u.used / u.total, 1)})
        except OSError:
            pass

    largest = sorted(sc.dirs, key=lambda d: d[1], reverse=True)
    largest = [{"path": p, "bytes": b} for p, b in largest if b >= opts.min_size][: opts.top]

    cats = sorted(by_cat.values(), key=lambda c: c["bytes"], reverse=True)
    reclaim_safe = sum(c["bytes"] for c in cats if c["risk"] == SAFE)
    reclaim_review = sum(c["bytes"] for c in cats if c["risk"] == REVIEW)

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": os.environ.get("COMPUTERNAME") or os.uname().nodename if hasattr(os, "uname") else "",
        "roots": [os.path.abspath(r) for r in roots],
        "options": {k: v for k, v in asdict(opts).items()},
        "drives": drives,
        "totals": {
            "scanned_bytes": sc.total_bytes, "dirs": sc.n_dirs, "files": sc.n_files,
            "reclaimable_safe": reclaim_safe, "reclaimable_review": reclaim_review,
            "links_skipped": sc.links_skipped, "errors": len(sc.errors),
            "elapsed_s": round(time.time() - sc._t0, 1),
        },
        "categories": cats,
        "findings": [asdict(f) for f in sorted(sc.findings, key=lambda f: f.bytes, reverse=True)],
        "largest_dirs": largest,
        "large_files": sorted(sc.large_files, key=lambda f: f["bytes"], reverse=True)[:100],
        "system_files": sc.system_files,
        "virtual_disks": vh,
        "git_repos": [asdict(r) for r in sorted(sc.repos, key=lambda r: r.git_bytes,
                                                reverse=True)[:50]],
        "duplicates": dupes[:200],
        "errors": sc.errors[:200],
    }


def print_report(rep: dict) -> None:
    t = rep["totals"]
    print()
    print("=" * 78)
    print(f"  DISK AUDIT  {rep['generated_at']}")
    print(f"  roots: {', '.join(rep['roots'])}")
    print("=" * 78)
    if rep["drives"]:
        print("\nVOLUMES")
        print(_table([[d["drive"], human(d["total"]), human(d["used"]),
                       human(d["free"]), f"{d['used_pct']}%"] for d in rep["drives"]],
                     ["DRIVE", "TOTAL", "USED", "FREE", "FULL"], "lrrrr"))
    print(f"scanned {human(t['scanned_bytes'])} across {t['dirs']:,} dirs / "
          f"{t['files']:,} files in {t['elapsed_s']}s "
          f"({t['links_skipped']:,} junction/symlink skipped, {t['errors']} unreadable)")

    print("\nRECLAIMABLE BY CATEGORY")
    rows = [[c["category"], c["risk"], f"{c['count']:,}", human(c["bytes"]), shorten(c["action"], 52)]
            for c in rep["categories"]]
    print(_table(rows, ["CATEGORY", "RISK", "ITEMS", "SIZE", "HOW TO RECLAIM"], "llrrl"))
    print(f"  => SAFE   (delete freely) : {human(t['reclaimable_safe'])}")
    print(f"  => REVIEW (confirm first) : {human(t['reclaimable_review'])}")

    print("\nTOP FINDINGS")
    rows = [[human(f["bytes"]), f["risk"], f["category"], shorten(f["path"], 88)]
            for f in rep["findings"][:25]]
    print(_table(rows, ["SIZE", "RISK", "CATEGORY", "PATH"], "rlll"))

    print("\nLARGEST DIRECTORIES")
    rows = [[human(d["bytes"]), shorten(d["path"], 96)] for d in rep["largest_dirs"]]
    print(_table(rows, ["SIZE", "PATH"], "rl"))

    if rep["git_repos"]:
        rows = [[human(r["git_bytes"]), human(r["worktree_bytes"]), str(r["ratio"]),
                 shorten(r["verdict"] or "ok", 30), shorten(r["path"], 60)]
                for r in rep["git_repos"][:15]]
        print("\nGIT REPOSITORIES (.git vs working tree)")
        print(_table(rows, [".GIT", "WORKTREE", "RATIO", "VERDICT", "REPO"], "rrlll"))

    if rep["virtual_disks"]:
        print("\nVIRTUAL DISKS (WSL / Docker) — grow-only, NEVER delete blind")
        print(_table([[human(v["bytes"]), shorten(v["path"], 88)] for v in rep["virtual_disks"][:10]],
                     ["SIZE", "PATH"], "rl"))

    if rep["large_files"]:
        print("\nLARGE LOOSE FILES")
        print(_table([[human(f["bytes"]), f["mtime"], shorten(f["path"], 80)]
                      for f in rep["large_files"][:20]],
                     ["SIZE", "MTIME", "PATH"], "rll"))

    if rep["system_files"]:
        print("\nSYSTEM FILES — report only, NEVER deletable by this tool")
        print(_table([[human(f["bytes"]), shorten(f["path"], 40), shorten(f["action"], 70)]
                      for f in rep["system_files"]],
                     ["SIZE", "PATH", "HOW TO SHRINK"], "rll"))

    if rep["duplicates"]:
        print("\nDUPLICATES (same size + same sha256)")
        rows = []
        for d in rep["duplicates"][:15]:
            rows.append([human(d["reclaimable"]), str(d["copies"]), shorten(d["paths"][0], 74)])
            for p in d["paths"][1:3]:
                rows.append(["", "", "  = " + shorten(p, 72)])
        print(_table(rows, ["RECLAIM", "COPIES", "PATHS"], "rrl"))

    if rep["errors"]:
        print(f"\n{len(rep['errors'])} unreadable path(s) (permission denied / in use); "
              f"first few:")
        for e in rep["errors"][:5]:
            print(f"  - {e['path']}  ({e['error']})")
    print("\nNothing was deleted. `scan` is read-only.")
    print("To delete, review the JSON then run: diskaudit.py clean --from <report.json> "
          "--category <cat> --yes-delete-for-real\n")


def write_markdown(rep: dict, path: str) -> None:
    today = rep["generated_at"][:10]
    L: list[str] = []
    L.append("---")
    L.append(f"title: Disk audit — {', '.join(rep['roots'])}")
    L.append("type: source")
    L.append(f"created: {today}")
    L.append(f"updated: {today}")
    L.append("sources: [diskaudit.py]")
    L.append("tags: [disk, storage, cleanup, windows]")
    L.append("---\n")
    L.append(f"# Disk audit — {', '.join(rep['roots'])}\n")
    L.append(f"Generated {rep['generated_at']} · scanned {human(rep['totals']['scanned_bytes'])} "
             f"in {rep['totals']['dirs']:,} directories.\n")
    if rep["drives"]:
        L.append("## Volumes\n")
        L.append("| Drive | Total | Used | Free | Full |")
        L.append("|---|---|---|---|---|")
        for d in rep["drives"]:
            L.append(f"| {d['drive']} | {human(d['total'])} | {human(d['used'])} | "
                     f"{human(d['free'])} | {d['used_pct']}% |")
        L.append("")
    L.append("## Reclaimable by category\n")
    L.append("| Category | Risk | Items | Size | How to reclaim |")
    L.append("|---|---|---|---|---|")
    for c in rep["categories"]:
        L.append(f"| `{c['category']}` | **{c['risk']}** | {c['count']:,} | "
                 f"{human(c['bytes'])} | {c['action']} |")
    L.append("")
    L.append(f"- **SAFE total**: {human(rep['totals']['reclaimable_safe'])}")
    L.append(f"- **REVIEW total**: {human(rep['totals']['reclaimable_review'])}\n")
    L.append("## Top findings\n")
    L.append("| Size | Risk | Category | Path |")
    L.append("|---|---|---|---|")
    for f in rep["findings"][:40]:
        L.append(f"| {human(f['bytes'])} | {f['risk']} | `{f['category']}` | `{f['path']}` |")
    L.append("")
    L.append("## Largest directories\n")
    L.append("| Size | Path |")
    L.append("|---|---|")
    for d in rep["largest_dirs"]:
        L.append(f"| {human(d['bytes'])} | `{d['path']}` |")
    L.append("")
    if rep["git_repos"]:
        L.append("## Git repositories\n")
        L.append("| .git | Worktree | Ratio | Verdict | Repo |")
        L.append("|---|---|---|---|---|")
        for r in rep["git_repos"][:20]:
            L.append(f"| {human(r['git_bytes'])} | {human(r['worktree_bytes'])} | "
                     f"{r['ratio']} | {r['verdict'] or 'ok'} | `{r['path']}` |")
        L.append("")
    if rep["virtual_disks"]:
        L.append("## Virtual disks (WSL / Docker)\n")
        L.append("> These grow and never shrink on their own. Deleting a `.vhdx` destroys the "
                 "distro or the container data inside it. Compact, do not delete.\n")
        for v in rep["virtual_disks"][:10]:
            L.append(f"- `{v['path']}` — {human(v['bytes'])} — {v['action']}")
        L.append("")
    if rep["system_files"]:
        L.append("## System files (never delete)\n")
        for f in rep["system_files"]:
            L.append(f"- `{f['path']}` — {human(f['bytes'])} — {f['action']}")
        L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def opts_from_args(a) -> Options:
    return Options(depth=a.depth, top=a.top, min_size=parse_size(a.min_size),
                   large_file=parse_size(a.large_file), dupes=getattr(a, "dupes", False),
                   dupe_min=parse_size(getattr(a, "dupe_min", "1MB")),
                   on_disk=getattr(a, "on_disk", False), git=not getattr(a, "no_git", False),
                   exclude=list(getattr(a, "exclude", []) or []), quiet=a.quiet,
                   vhdx=getattr(a, "vhdx", False))


def _covers_profile(roots: list[str]) -> bool:
    """True if any root is a volume root or an ancestor of the user profile."""
    home = norm(os.path.expanduser("~"))
    for r in roots:
        q = norm(r)
        if len([p for p in os.path.splitdrive(q)[1].split(os.sep) if p]) == 0:
            return True                                   # a whole volume
        if home == q or home.startswith(q + os.sep):
            return True
    return False


def cmd_scan(a) -> int:
    roots = [os.path.abspath(r) for r in a.roots]
    for r in roots:
        if not os.path.isdir(r):
            sys.exit(f"not a directory: {r}")
    o = opts_from_args(a)
    if not a.no_vhdx and (a.vhdx or _covers_profile(roots)):
        o.vhdx = True
    sc = Scanner(o)
    for r in roots:
        if not o.quiet:
            print(f"[scan] {r}", file=sys.stderr)
        sc.walk(r)
    sc.probe_git()
    dupes = sc.find_dupes() if o.dupes else []
    rep = build_report(roots, sc, dupes, o)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        print(f"[json] {os.path.abspath(a.json)}", file=sys.stderr)
    if a.markdown:
        write_markdown(rep, a.markdown)
        print(f"[markdown] {os.path.abspath(a.markdown)}", file=sys.stderr)
    if not a.json_only:
        print_report(rep)
    return 0


def cmd_caches(a) -> int:
    build_known_paths()
    rows = []
    findings = []
    for p, (cat, risk, note, action) in sorted(KNOWN.items()):
        if cat not in ("pkg_cache",):
            continue
        if not os.path.isdir(p):
            continue
        b, n = dir_size(p, a.on_disk)
        if b < parse_size(a.min_size):
            continue
        findings.append({"path": KNOWN_DISPLAY.get(p, p), "category": cat, "risk": risk,
                         "bytes": b, "files": n, "note": note, "action": action})
    findings.sort(key=lambda f: f["bytes"], reverse=True)
    total = sum(f["bytes"] for f in findings)
    rows = [[human(f["bytes"]), f["risk"], shorten(f["action"], 44), shorten(f["path"], 64)] for f in findings]
    print("\nPACKAGE-MANAGER / APP CACHES\n")
    print(_table(rows, ["SIZE", "RISK", "HOW TO CLEAR", "PATH"], "rlll"))
    print(f"  total: {human(total)}   (all re-downloadable; clearing breaks offline builds)\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA, "generated_at": datetime.now().astimezone().isoformat(),
                       "categories": [{"category": "pkg_cache", "risk": SAFE,
                                       "count": len(findings), "bytes": total,
                                       "action": "clear with the package manager",
                                       "note": "re-downloadable"}],
                       "findings": findings, "roots": [], "drives": [], "largest_dirs": [],
                       "large_files": [], "system_files": [], "virtual_disks": [],
                       "git_repos": [], "duplicates": [], "errors": [],
                       "totals": {"reclaimable_safe": total}}, f, indent=2, ensure_ascii=False)
        print(f"[json] {os.path.abspath(a.json)}", file=sys.stderr)
    return 0


def cmd_windows(a) -> int:
    if not IS_WIN:
        sys.exit("`windows` only makes sense on Windows")
    build_known_paths()
    findings = []
    for p, (cat, risk, note, action) in sorted(KNOWN.items()):
        if cat not in ("windows_junk", "docker_wsl", "appx_packages", "temp_dir", "ide_cache"):
            continue
        if not os.path.isdir(p):
            continue
        b, n = dir_size(p, a.on_disk)
        findings.append({"path": KNOWN_DISPLAY.get(p, p), "category": cat, "risk": risk,
                         "bytes": b, "files": n, "note": note, "action": action})
    sysfiles = []
    for drive in _volumes():
        for name, (note, action) in SYSTEM_FILES.items():
            fp = os.path.join(drive, name)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            sysfiles.append({"path": fp, "bytes": st.st_size, "note": note,
                             "action": action, "risk": NEVER})
    vh = find_vhdx(a.on_disk)
    findings.sort(key=lambda f: f["bytes"], reverse=True)

    print("\nWINDOWS JUNK\n")
    print(_table([[human(f["bytes"]), f["risk"], shorten(f["action"], 46), shorten(f["path"], 60)]
                  for f in findings], ["SIZE", "RISK", "HOW TO RECLAIM", "PATH"], "rlll"))
    print("\nVIRTUAL DISKS (WSL / Docker)\n")
    print(_table([[human(v["bytes"]), shorten(v["path"], 88)] for v in vh], ["SIZE", "PATH"], "rl"))
    if vh:
        print("  ! deleting a .vhdx destroys the WSL distro / Docker data inside it.")
        print("  ! reclaim with: wsl --shutdown ; wsl --manage <distro> --set-sparse true")
        print("    (or diskpart: select vdisk file=\"...\" ; attach vdisk readonly ; "
              "compact vdisk ; detach vdisk)\n")
    print("SYSTEM FILES — size only, this tool can never delete these\n")
    print(_table([[human(f["bytes"]), f["path"], shorten(f["action"], 66)] for f in sysfiles],
                 ["SIZE", "PATH", "HOW TO SHRINK"], "rll"))
    claimed = [os.path.normcase(f["path"]) for f in findings]
    total_r = (sum(f["bytes"] for f in findings if f["risk"] != NEVER)
               + sum(v["bytes"] for v in vh if not _covered_by(v["path"], claimed)))
    vh_total = sum(v["bytes"] for v in vh)
    print(f"\n  potentially reclaimable (REVIEW): {human(total_r)}")
    print(f"  of which virtual disks (compact, do not delete): {human(vh_total)}")
    print(f"  system files above are NOT part of that total.\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA,
                       "generated_at": datetime.now().astimezone().isoformat(),
                       "findings": findings, "system_files": sysfiles, "virtual_disks": vh,
                       "categories": [], "roots": [], "drives": [], "largest_dirs": [],
                       "large_files": [], "git_repos": [], "duplicates": [], "errors": [],
                       "totals": {"reclaimable_review": total_r}},
                      f, indent=2, ensure_ascii=False)
        print(f"[json] {os.path.abspath(a.json)}", file=sys.stderr)
    return 0


def _volumes() -> list[str]:
    if not IS_WIN:
        return ["/"]
    out = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return ["C:\\"]
    for i in range(26):
        if mask & (1 << i):
            out.append(f"{chr(65 + i)}:\\")
    return out


def cmd_repos(a) -> int:
    root = os.path.abspath(a.root)
    if not shutil.which("git"):
        sys.exit("git not found on PATH")
    rows = []
    try:
        entries = sorted(os.scandir(long_path(root)), key=lambda e: e.name)
    except OSError as e:
        sys.exit(f"cannot read {root}: {e}")
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False) or is_reparse(e.stat(follow_symlinks=False)):
                continue
        except OSError:
            continue
        gitdir = os.path.join(e.path, ".git")
        if not os.path.isdir(gitdir):
            continue
        gb, _ = dir_size(gitdir, a.on_disk)
        tb, _ = dir_size(e.path, a.on_disk)
        wb = max(tb - gb, 0)
        ratio = round(gb / wb, 2) if wb else float("inf")
        info = _git_count_objects(e.path) if gb >= parse_size(a.min_size) else {}
        verdict = "ok"
        if gb >= parse_size(a.min_size) and (ratio > 2 or gb > 500 * (1 << 20)):
            verdict = "gc candidate"
        rows.append({"path": display(e.path), "total_bytes": tb, "git_bytes": gb,
                     "worktree_bytes": wb, "ratio": ratio, "verdict": verdict,
                     "loose_objects": info.get("count", 0), "packs": info.get("packs", 0),
                     "size_pack": info.get("size-pack", ""), "size_loose": info.get("size", "")})
    rows.sort(key=lambda r: r["git_bytes"], reverse=True)
    print("\nGIT REPO FOREST — .git vs working tree\n")
    print(_table([[human(r["git_bytes"]), human(r["worktree_bytes"]), str(r["ratio"]),
                   f"{r['loose_objects']:,}", r["verdict"], shorten(os.path.basename(r["path"]), 38)]
                  for r in rows[: a.top]],
                 [".GIT", "WORKTREE", "RATIO", "LOOSE", "VERDICT", "REPO"], "rrlrll"))
    cand = [r for r in rows if r["verdict"] != "ok"]
    print(f"  {len(rows)} repos · .git total {human(sum(r['git_bytes'] for r in rows))} · "
          f"{len(cand)} gc candidate(s)\n")
    if cand:
        print("  Repack them (NEVER delete .git):")
        for r in cand[:10]:
            print(f'    git -C "{r["path"]}" gc --aggressive --prune=now')
        print()
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA, "root": root, "git_repos": rows}, f, indent=2,
                      ensure_ascii=False)
        print(f"[json] {os.path.abspath(a.json)}", file=sys.stderr)
    return 0


def cmd_dupes(a) -> int:
    o = Options(depth=0, dupes=True, dupe_min=parse_size(a.dupe_min), quiet=a.quiet,
                large_file=1 << 62, min_size=1 << 62,
                exclude=list(a.exclude or []), git=False)
    sc = Scanner(o)
    for r in a.roots:
        sc.walk(os.path.abspath(r))
    dupes = sc.find_dupes()
    total = sum(d["reclaimable"] for d in dupes)
    print("\nEXACT DUPLICATES (size group -> sha256)\n")
    for d in dupes[: a.top]:
        print(f"  {human(d['bytes_each'])} x{d['copies']}  (reclaim {human(d['reclaimable'])})")
        for p in d["paths"]:
            print(f"      {p}")
        print()
    print(f"  {len(dupes)} duplicate set(s) · reclaimable {human(total)}\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA, "duplicates": dupes,
                       "totals": {"reclaimable_review": total}}, f, indent=2, ensure_ascii=False)
    return 0


def cmd_clean(a) -> int:
    """The ONLY code path that removes anything. Guarded five ways."""
    with open(a.source, encoding="utf-8") as f:
        rep = json.load(f)
    if rep.get("schema") != SCHEMA:
        sys.exit(f"{a.source} is not a disk-audit report (schema={rep.get('schema')!r})")
    wanted = {c.strip() for c in a.category.split(",") if c.strip()}
    unknown = wanted - DELETABLE_CATEGORIES
    if unknown:
        sys.exit(f"category not deletable by this tool: {', '.join(sorted(unknown))}\n"
                 f"deletable categories: {', '.join(sorted(DELETABLE_CATEGORIES))}")

    targets, rejected = [], []
    for f in rep.get("findings", []):
        if f["category"] not in wanted:
            continue
        if f["risk"] != SAFE:                            # guard 1: SAFE only
            rejected.append((f["path"], f"risk={f['risk']}"))
            continue
        p = f["path"]
        if not os.path.isdir(p):                         # guard 2: still exists
            rejected.append((p, "gone since the scan"))
            continue
        why = is_protected(p)                            # guard 3: protected paths
        if why:
            rejected.append((p, why))
            continue
        again = classify_dir(os.path.basename(p.rstrip("\\/")), p,
                             os.path.dirname(p))          # guard 4: re-verify class
        if not again or again[0] != f["category"] or again[1] != SAFE:
            rejected.append((p, "no longer classifies as this SAFE category"))
            continue
        live, nfiles = dir_size(p, False)
        targets.append({"path": p, "category": f["category"], "bytes": live, "files": nfiles})

    if rejected:
        print(f"\nSKIPPED {len(rejected)} finding(s):")
        for p, why in rejected[:20]:
            print(f"  - {p}\n      {why}")
    if not targets:
        print("\nNothing to delete.\n")
        return 0

    total = sum(t["bytes"] for t in targets)
    print("\n" + "=" * 78)
    print(f"  ABOUT TO REMOVE {len(targets)} DIRECTORIES — {human(total)}")
    print("=" * 78)
    for t in targets:
        print(f"  {human(t['bytes']):>12}  [{t['category']}]  {t['path']}")
    print("=" * 78)
    mode = "PERMANENT DELETE (no Recycle Bin, NOT undoable)" if a.permanent else \
           "Recycle Bin (undoable — but see the warning below)"
    print(f"  mode : {mode}")
    if not a.permanent:
        print("  !!  The shell API is MAX_PATH-bound: deep node_modules trees may refuse to")
        print("  !!  recycle. Items larger than the Recycle Bin quota are deleted")
        print("  !!  PERMANENTLY and SILENTLY by Windows. Treat this as irreversible.")
    else:
        print("  !!  THIS IS PERMANENT. There is no Recycle Bin copy. There is no undo.")
    print(f"  free : {human(total)} will be reclaimed")
    print("=" * 78)

    if a.dry_run:
        print("\n--dry-run: nothing was touched.\n")
        return 0
    if not a.yes_delete_for_real:                        # guard 5: explicit flag
        print("\nRefusing to delete: pass --yes-delete-for-real to arm the command.\n")
        return 1
    if not sys.stdin or not sys.stdin.isatty():
        print("\nRefusing to delete: stdin is not a terminal, so the typed confirmation "
              "cannot be collected. Run it interactively.\n")
        return 1
    try:
        answer = input('\nType exactly  DELETE  to proceed (anything else aborts): ')
    except (EOFError, KeyboardInterrupt):
        print("\naborted.\n")
        return 1
    if answer.strip() != "DELETE":
        print("aborted.\n")
        return 1

    ts = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    logpath = a.log or os.path.join(os.path.dirname(os.path.abspath(a.source)),
                                    f"disk-audit-deletions-{ts}.jsonl")
    freed = 0
    ok_n = fail_n = 0
    with open(logpath, "a", encoding="utf-8") as log:
        for t in targets:
            if a.permanent:
                ok, msg = permanent_delete(t["path"])
            else:
                ok, msg = recycle([t["path"]])
                if not ok:
                    msg += " (retry with --permanent, or shorten the path)"
            if ok:
                freed += t["bytes"]
                ok_n += 1
            else:
                fail_n += 1
            log.write(json.dumps({
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "path": t["path"], "category": t["category"], "bytes": t["bytes"],
                "files": t["files"], "mode": "permanent" if a.permanent else "recycle",
                "ok": ok, "message": msg, "report": os.path.abspath(a.source),
            }, ensure_ascii=False) + "\n")
            print(f"  {'OK ' if ok else 'FAIL'}  {human(t['bytes']):>12}  {t['path']}"
                  + ("" if ok else f"\n         {msg}"))
    print(f"\nremoved {ok_n} / {len(targets)} · freed {human(freed)} · {fail_n} failure(s)")
    print(f"log: {logpath}\n")
    return 0 if fail_n == 0 else 2


def cmd_selftest(a) -> int:
    """Non-destructive checks of the risky machinery. Deletes nothing, ever."""
    checks: list[tuple[str, bool, str]] = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    chk("parse_size", parse_size("500MB") == 500 * (1 << 20) and parse_size("2GB") == 2 * (1 << 30),
        f"{parse_size('500MB')}")
    chk("human", human(1536) == "1.5 KB", human(1536))
    if IS_WIN:
        chk("SHFILEOPSTRUCTW layout (x64 = 56 bytes)",
            ctypes.sizeof(SHFILEOPSTRUCTW) == (56 if ctypes.sizeof(ctypes.c_void_p) == 8 else 32),
            f"sizeof={ctypes.sizeof(SHFILEOPSTRUCTW)}")
        # Exercise the API against a path that cannot exist: proves the call
        # marshals and returns a code, WITHOUT touching any real file.
        ok, msg = recycle([os.path.join(os.path.abspath(os.sep),
                                        "__diskaudit_nonexistent__", "x")])
        chk("SHFileOperationW callable (no-op on a missing path)", not ok and "code" in msg, msg)
        chk("long_path prefix", long_path("C:\\x").startswith("\\\\?\\"), long_path("C:\\x"))
        chk("cluster_size", cluster_size("C:\\") >= 512, str(cluster_size("C:\\")))
    # protection guards
    for bad in [os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
                os.path.join(os.path.expanduser("~"), "Documents"),
                "C:\\", r"C:\$Recycle.Bin\x"]:
        chk(f"protected: {bad}", is_protected(bad) is not None, str(is_protected(bad)))
    chk("node_modules not protected",
        is_protected(os.path.join(os.path.abspath(os.sep), "proj", "app", "node_modules")) is None,
        str(is_protected(os.path.join(os.path.abspath(os.sep), "proj", "app", "node_modules"))))
    chk("deletable set excludes build_output/git/system",
        not ({"build_output", "git_bloat", "windows_junk", "system", "docker_wsl",
              "python_env", "dotnet_output"} & DELETABLE_CATEGORIES))
    build_known_paths()
    chk("known cache paths registered", len(KNOWN) > 25, f"{len(KNOWN)} paths")
    width = max(len(c[0]) for c in checks)
    print()
    bad = 0
    for name, ok, detail in checks:
        if not ok:
            bad += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\n  {len(checks) - bad}/{len(checks)} passed\n")
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="diskaudit.py",
        description="Find what is eating a Windows disk and what is safe to reclaim. "
                    "Read-only unless you run `clean`.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="full audit of one or more roots")
    s.add_argument("roots", nargs="+")
    s.add_argument("--depth", type=int, default=3, help="depth of the largest-dirs ranking (3)")
    s.add_argument("--top", type=int, default=25, help="rows in the ranking (25)")
    s.add_argument("--min-size", default="100MB", help="ignore dirs below this in the ranking")
    s.add_argument("--large-file", default="500MB", help="loose-file threshold (500MB)")
    s.add_argument("--dupes", action="store_true", help="also hunt exact duplicates (slower)")
    s.add_argument("--dupe-min", default="1MB", help="ignore files below this for dupes")
    s.add_argument("--on-disk", action="store_true",
                   help="round file sizes up to the cluster (real size on disk)")
    s.add_argument("--no-git", action="store_true", help="skip `git count-objects` probing")
    s.add_argument("--vhdx", action="store_true",
                   help="also hunt WSL/Docker virtual disks under the user profile "
                        "(automatic when a root covers it)")
    s.add_argument("--no-vhdx", action="store_true", help="never hunt virtual disks")
    s.add_argument("--exclude", action="append", default=[], help="glob to skip (repeatable)")
    s.add_argument("--json", help="write the machine-readable report here")
    s.add_argument("--markdown", help="write a second-brain-ready summary here")
    s.add_argument("--json-only", action="store_true", help="suppress the terminal report")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("caches", help="size known package-manager / app caches (fast)")
    c.add_argument("--min-size", default="10MB")
    c.add_argument("--on-disk", action="store_true")
    c.add_argument("--json")
    c.set_defaults(func=cmd_caches)

    w = sub.add_parser("windows", help="Windows junk + WSL/Docker vhdx + pagefile (fast)")
    w.add_argument("--on-disk", action="store_true")
    w.add_argument("--json")
    w.set_defaults(func=cmd_windows)

    r = sub.add_parser("repos", help=".git bloat ranking across a repo forest")
    r.add_argument("root")
    r.add_argument("--top", type=int, default=30)
    r.add_argument("--min-size", default="100MB", help="probe git only above this .git size")
    r.add_argument("--on-disk", action="store_true")
    r.add_argument("--json")
    r.set_defaults(func=cmd_repos)

    d = sub.add_parser("dupes", help="exact duplicate finder")
    d.add_argument("roots", nargs="+")
    d.add_argument("--dupe-min", default="1MB")
    d.add_argument("--top", type=int, default=30)
    d.add_argument("--exclude", action="append", default=[])
    d.add_argument("--json")
    d.add_argument("--quiet", action="store_true")
    d.set_defaults(func=cmd_dupes)

    k = sub.add_parser("clean", help="remove SAFE findings from a report (guarded)")
    k.add_argument("--from", dest="source", required=True, help="report.json from `scan`")
    k.add_argument("--category", required=True,
                   help="comma list; only " + ",".join(sorted(DELETABLE_CATEGORIES)))
    k.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    k.add_argument("--permanent", action="store_true",
                   help="skip the Recycle Bin — IRREVERSIBLE")
    k.add_argument("--yes-delete-for-real", action="store_true",
                   help="arm the command (a typed DELETE is still required)")
    k.add_argument("--log", help="deletion log path (default: next to the report)")
    k.set_defaults(func=cmd_clean)

    t = sub.add_parser("selftest", help="verify the risky machinery; deletes nothing")
    t.set_defaults(func=cmd_selftest)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except KeyboardInterrupt:
        print("\ninterrupted (nothing was deleted)\n", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    raise SystemExit(main())
