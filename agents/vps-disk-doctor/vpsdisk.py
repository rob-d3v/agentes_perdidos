#!/usr/bin/env python3
"""vps-disk-doctor — find out what is filling a Linux/Docker/Coolify VPS disk, over SSH.

stdlib only. Runs on your workstation; everything remote goes through one `ssh` call
per command. `scan` is read-only. `clean` is the only thing that removes anything, it
accepts only SAFE actions, and it needs --armed plus --confirm <remote hostname>.

    python vpsdisk.py scan  --host root@1.2.3.4 -i ~/.ssh/key [--json out.json] [--markdown out.md]
    python vpsdisk.py clean --host root@1.2.3.4 -i ~/.ssh/key --only builder,dangling \
                            --armed --confirm <hostname>

Env fallbacks: VPSDISK_HOST, VPSDISK_KEY.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- remote probe
# One bash script, sections delimited by "@@@name". Every command is read-only.
PROBE = r"""
export LC_ALL=C
s(){ echo "@@@$1"; }
s hostname;   hostname
s df;         df -B1 --output=size,used,avail,pcent / | tail -1
s inodes;     df --output=ipcent / | tail -1
s top;        du -x -B1 --max-depth=1 / 2>/dev/null | sort -rn | head -15
s docker_top; du -x -B1 --max-depth=1 /var/lib/docker 2>/dev/null | sort -rn | head -10
s sysdf;      docker system df --format '{{json .}}' 2>/dev/null
s dangling_images; docker images -f dangling=true --format '{{.ID}}' 2>/dev/null | wc -l
s orphan_volumes
for v in $(docker volume ls -qf dangling=true 2>/dev/null); do
  p=/var/lib/docker/volumes/$v/_data
  sz=$(du -sB1 "$p" 2>/dev/null | cut -f1)
  last=$(find "$p" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1)
  echo "${sz:-0} ${last:-0} $v"
done | sort -rn
s container_logs
for f in /var/lib/docker/containers/*/*-json.log; do [ -f "$f" ] && echo "$(stat -c %s "$f") $f"; done 2>/dev/null | sort -rn | head -8
s log_driver; docker info --format '{{.LoggingDriver}}' 2>/dev/null; cat /etc/docker/daemon.json 2>/dev/null | tr -d '\n'
s journal;    journalctl --disk-usage 2>/dev/null
s varlog;     find /var/log -xdev -type f -size +50M -printf '%s %p\n' 2>/dev/null | sort -rn | head -8
s backups
for d in /root/backups /var/backups /opt/backups /backup /backups /data/coolify/backups /home/*/backups; do
  [ -d "$d" ] && echo "$(du -sB1 "$d" 2>/dev/null | cut -f1) $(find "$d" -type f 2>/dev/null | wc -l) $d"
done
s bigfiles;   find / -xdev -type f -size +1G -not -path '/var/lib/docker/overlay2/*' -not -path '/proc/*' -printf '%s %TY-%Tm-%Td %p\n' 2>/dev/null | sort -rn | head -15
s deleted_open
for p in /proc/[0-9]*/fd/*; do
  t=$(readlink "$p" 2>/dev/null) || continue
  case "$t" in *'(deleted)'*) echo "$(stat -Lc %s "$p" 2>/dev/null || echo 0) $(cat /proc/$(echo $p|cut -d/ -f3)/comm 2>/dev/null) $t";; esac
done | sort -rn | head -8
s swap;       swapon --show=NAME,SIZE --bytes --noheadings 2>/dev/null
s apt;        du -sB1 /var/cache/apt 2>/dev/null | cut -f1
s cron;       crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$'; cat /etc/cron.d/* 2>/dev/null | grep -v '^#' | grep -vE '^(SHELL|PATH|MAILTO)=' | grep -v '^$'
s cleanup_history; tail -40 /var/log/docker-cleanup.log 2>/dev/null | grep -E '^/dev/|reclaimed'
echo "@@@end"
"""

CLEAN_ACTIONS = {
    # key: (risk, what, command)
    "builder":  ("SAFE", "Docker build cache (rebuilt on next deploy, slower first build)",
                 "docker builder prune -af"),
    "dangling": ("SAFE", "dangling <none> images (no tag, no container)",
                 "docker image prune -f"),
    "journal":  ("SAFE", "systemd journal down to 200M",
                 "journalctl --vacuum-size=200M"),
    "apt":      ("SAFE", "apt package cache",
                 "apt-get clean"),
}


def human(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}TB"


def parse_size(s: str) -> float:
    """'21.28GB' / '162.8MB' / '0B' -> bytes (docker uses powers of 1000)."""
    m = re.match(r"([\d.]+)\s*([KMGT]?B)", s.strip())
    if not m:
        return 0.0
    mult = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2)]
    return float(m.group(1)) * mult


def ssh(args, script: str, timeout: int = 900) -> str:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if args.key:
        cmd += ["-i", os.path.expanduser(args.key)]
    cmd += [args.host, "bash -s"]
    # bytes, not text: text mode on Windows turns \n into \r\n and bash chokes on it
    r = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True, timeout=timeout)
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0 and "@@@" not in out:
        sys.exit(f"ssh failed ({r.returncode}): {r.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return out


def sections(raw: str) -> dict[str, list[str]]:
    out, cur = {}, None
    for line in raw.splitlines():
        if line.startswith("@@@"):
            cur = line[3:].strip()
            out[cur] = []
        elif cur:
            out[cur].append(line.rstrip())
    return out


# ---------------------------------------------------------------- classification
def analyse(sec: dict[str, list[str]]) -> dict:
    now = dt.datetime.now().timestamp()
    size, used, avail, pct = (sec.get("df") or ["0 0 0 0%"])[0].split()
    rep = {
        "host": (sec.get("hostname") or ["?"])[0],
        "scanned_at": dt.datetime.now().isoformat(timespec="seconds"),
        "disk": {"size": int(size), "used": int(used), "avail": int(avail), "pct": int(pct.rstrip("%")),
                 "inodes_pct": (sec.get("inodes") or ["?"])[0].strip()},
        "top": [(int(a), b) for a, b in (l.split(None, 1) for l in sec.get("top", []) if l.strip())],
        "docker_top": [(int(a), b) for a, b in (l.split(None, 1) for l in sec.get("docker_top", []) if l.strip())],
        "findings": [],
        "context": {},
    }
    F = rep["findings"]

    def add(cat, risk, nbytes, what, fix):
        F.append({"category": cat, "risk": risk, "bytes": int(nbytes), "what": what, "fix": fix})

    sysdf = {}
    for l in sec.get("sysdf", []):
        try:
            d = json.loads(l)
            sysdf[d["Type"]] = d
        except (ValueError, KeyError):
            pass
    rep["context"]["docker_system_df"] = sysdf

    bc = sysdf.get("Build Cache")
    if bc:
        rec = parse_size(bc["Reclaimable"].split()[0])
        if rec > 1e9:
            add("build_cache", "SAFE", rec, f"Docker build cache: {bc['TotalCount']} entries, {bc['Size']}",
                "`clean --only builder` now; prevent: daily `docker builder prune -af --filter until=24h`")
    img = sysdf.get("Images")
    ndang = int((sec.get("dangling_images") or ["0"])[0] or 0)
    if img:
        rec = parse_size(img["Reclaimable"].split()[0])
        if rec > 1e9:
            add("images_unused", "REVIEW", rec,
                f"{img['TotalCount']} images, {img['Active']} in use; {ndang} dangling <none>. "
                "Unused tagged images are what Coolify rolls back to",
                "`clean --only dangling` is safe; `docker image prune -af` also drops rollback targets — decide first")

    for l in sec.get("orphan_volumes", []):
        parts = l.split(None, 2)
        if len(parts) < 3:
            continue
        nb, last, name = int(parts[0]), int(parts[1]), parts[2]
        if nb < 50e6:
            continue
        age = (now - last) / 86400 if last else None
        stale = f"no file written for {age:.0f} days" if age else "empty"
        add("orphan_volume", "REVIEW", nb,
            f"volume `{name}` is mounted by NO container ({stale})",
            "find out why it was detached (app moved to object storage? compose edit dropped a mount = live data "
            "now inside the container!). Archive off-box, exclude from backups, then `docker volume rm` by hand")

    for l in sec.get("container_logs", []):
        nb, path = l.split(None, 1)
        if int(nb) > 500e6:
            add("container_log", "REVIEW", int(nb), f"json-file log {path}",
                "`truncate -s0` it; prevent: log-opts max-size=50m max-file=3 in /etc/docker/daemon.json")
    drv = sec.get("log_driver", [])
    rep["context"]["log_driver"] = " ".join(drv)
    if drv and "json-file" in drv[0] and "max-size" not in " ".join(drv):
        add("log_rotation", "REVIEW", 0, "Docker json-file logs have NO global max-size (unbounded growth)",
            'set {"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"3"}} in daemon.json '
            "(applies to containers created afterwards)")

    j = " ".join(sec.get("journal", []))
    m = re.search(r"([\d.]+)([KMGT])", j)
    if m:
        jb = float(m.group(1)) * {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)]
        if jb > 500e6:
            add("journal", "SAFE", jb, f"systemd journal {human(jb)}", "`clean --only journal`; SystemMaxUse=200M")

    for l in sec.get("varlog", []):
        nb, path = l.split(None, 1)
        add("var_log", "REVIEW", int(nb), f"big log {path}", "rotate/truncate; check logrotate for it")

    backup_dirs = []
    for l in sec.get("backups", []):
        nb, nfiles, path = l.split(None, 2)
        backup_dirs.append(path.rstrip("/") + "/")
        if int(nb) > 500e6:
            add("local_backups", "REVIEW", int(nb), f"{path}: {nfiles} files kept ON the disk being backed up",
                "keep backups off-box only (B2/S3); if the tool stages locally, peak = previous + current set "
                "during the run — delete the previous set BEFORE writing the new one, or stream to the bucket")

    for l in sec.get("bigfiles", []):
        nb, date, path = l.split(None, 2)
        if "/swap" in path or any(path.startswith(b) for b in backup_dirs):
            continue  # swap and backup sets are reported by their own findings
        add("big_file", "REVIEW", int(nb), f"{path} (modified {date})", "triage by hand")

    for l in sec.get("deleted_open", []):
        parts = l.split(None, 2)
        if len(parts) == 3 and int(parts[0]) > 100e6:
            add("deleted_open", "REVIEW", int(parts[0]),
                f"process `{parts[1]}` holds a DELETED file open: {parts[2]} — df counts it, du does not",
                "restart that process/container to release the space")

    apt = int((sec.get("apt") or ["0"])[0] or 0)
    if apt > 300e6:
        add("apt_cache", "SAFE", apt, f"apt cache {human(apt)}", "`clean --only apt`")

    for l in sec.get("swap", []):
        if l.strip():
            name, nb = l.split()[:2]
            add("swap", "NEVER", int(nb), f"swap {name}", "sized on purpose; shrink only with a RAM plan")

    rep["context"]["cron"] = sec.get("cron", [])
    rep["context"]["cleanup_history"] = sec.get("cleanup_history", [])
    F.sort(key=lambda f: (-f["bytes"]))
    rep["safe_reclaimable"] = sum(f["bytes"] for f in F if f["risk"] == "SAFE")
    return rep


def to_markdown(rep: dict) -> str:
    d = rep["disk"]
    out = [f"# Disk report — {rep['host']} ({rep['scanned_at']})", "",
           f"**/ {d['pct']}% used** — {human(d['used'])} of {human(d['size'])}, {human(d['avail'])} free, "
           f"inodes {d['inodes_pct']}. SAFE reclaimable now: **{human(rep['safe_reclaimable'])}**.", "",
           "## Where the space is", "", "| Size | Path |", "|---:|---|"]
    out += [f"| {human(n)} | `{p}` |" for n, p in rep["top"][:10]]
    if rep["docker_top"]:
        out += ["", "| Size | /var/lib/docker |", "|---:|---|"]
        out += [f"| {human(n)} | `{p}` |" for n, p in rep["docker_top"][:6]]
    out += ["", "## Findings (biggest first)", "", "| Risk | Size | Category | What | Fix |", "|---|---:|---|---|---|"]
    for f in rep["findings"]:
        out.append(f"| {f['risk']} | {human(f['bytes'])} | {f['category']} | {f['what']} | {f['fix']} |")
    if rep["context"].get("cron"):
        out += ["", "## Scheduled jobs (correlate with alert times)", "", "```"] + rep["context"]["cron"] + ["```"]
    if rep["context"].get("cleanup_history"):
        out += ["", "## Past cleanup runs (df after each)", "", "```"] + rep["context"]["cleanup_history"][-8:] + ["```"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- commands
def cmd_scan(args):
    rep = analyse(sections(ssh(args, PROBE)))
    md = to_markdown(rep)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, ensure_ascii=False)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(md)
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


def cmd_clean(args):
    keys = [k.strip() for k in args.only.split(",") if k.strip()]
    bad = [k for k in keys if k not in CLEAN_ACTIONS]
    if bad:
        sys.exit(f"refusing: {bad} are not SAFE actions. Allowed: {', '.join(CLEAN_ACTIONS)}")
    print("Plan:")
    for k in keys:
        risk, what, command = CLEAN_ACTIONS[k]
        print(f"  [{risk}] {k:9} {what}\n            $ {command}")
    remote_host = ssh(args, "hostname").strip()
    if not args.armed:
        print(f"\nDry run on {remote_host}. Re-run with --armed --confirm {remote_host} to execute.")
        return
    if args.confirm != remote_host:
        sys.exit(f"refusing: --confirm must equal the remote hostname ({remote_host!r}).")
    body = ["set -u", "echo BEFORE; df -h / | tail -1"]
    for k in keys:
        body += [f"echo '== {k}'", CLEAN_ACTIONS[k][2] + " 2>&1 | tail -3"]
    body += ["echo AFTER; df -h / | tail -1",
             f"echo \"$(date -Is) vps-disk-doctor clean {','.join(keys)}\" >> /var/log/vps-disk-doctor.log"]
    print(ssh(args, "\n".join(body)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("VPSDISK_HOST"), help="user@host")
    ap.add_argument("-i", "--key", default=os.environ.get("VPSDISK_KEY"), help="ssh private key")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="read-only report")
    sc.add_argument("--json")
    sc.add_argument("--markdown")
    cl = sub.add_parser("clean", help="SAFE-only removal; dry run unless --armed")
    cl.add_argument("--only", required=True, help=",".join(CLEAN_ACTIONS))
    cl.add_argument("--armed", action="store_true")
    cl.add_argument("--confirm", help="must equal remote hostname")
    args = ap.parse_args()
    if not args.host:
        sys.exit("--host (or VPSDISK_HOST) is required")
    {"scan": cmd_scan, "clean": cmd_clean}[args.cmd](args)


if __name__ == "__main__":
    main()
