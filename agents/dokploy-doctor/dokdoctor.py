#!/usr/bin/env python3
"""dokploy-doctor — full health check of a Dokploy / Docker Swarm Linux VPS, over SSH.

stdlib only. Runs on your workstation. `report` opens ONE ssh session (fail2ban-friendly),
pipes a read-only bash probe to it and classifies the result. The disk part is not
duplicated here: it reuses the probe + classifier of ../vps-disk-doctor/vpsdisk.py.

    python dokdoctor.py --host ubuntu@1.2.3.4 -i ~/.ssh/key report [--json out.json] [--markdown out.md]
    python dokdoctor.py --host ubuntu@1.2.3.4 -i ~/.ssh/key clean --only builder,dangling \
                        [--armed --confirm <remote hostname>]

`report` is read-only. `clean` is the only command that removes anything: it accepts only
the SAFE actions of vps-disk-doctor, is a dry run unless --armed, and needs
--confirm <remote hostname>.

Non-root SSH users (Ubuntu images: `ubuntu`, `opc`) usually cannot talk to docker; the probe
runs under `sudo -n` automatically unless the user is root (--sudo auto|always|never).

Env fallbacks: DOKDOC_HOST / DOKDOC_KEY, then VPSDISK_HOST / VPSDISK_KEY.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- reuse vps-disk-doctor
_VPSDISK_PATH = Path(__file__).resolve().parent.parent / "vps-disk-doctor" / "vpsdisk.py"


def _load_vpsdisk():
    if not _VPSDISK_PATH.exists():
        sys.exit(f"missing sibling agent: {_VPSDISK_PATH}")
    spec = importlib.util.spec_from_file_location("vpsdisk", _VPSDISK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vpsdisk = _load_vpsdisk()
human = vpsdisk.human

# ---------------------------------------------------------------- remote probe (health)
# Sections are prefixed h_ so they never collide with vpsdisk's. Every command is read-only:
# /proc reads, `docker ps/inspect/info/service ls/service ps/stats/logs`, systemctl show/list,
# journalctl reads, du/find, and a local parse of Traefik's acme.json that prints ONLY
# domain + expiry (never keys).
HEALTH = r"""
export LC_ALL=C
s(){ echo "@@@$1"; }
s h_arch;     uname -m
s h_kernel;   uname -r
s h_os;       . /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}"
s h_uptime;   cut -d' ' -f1 /proc/uptime
s h_loadavg;  cat /proc/loadavg
s h_nproc;    nproc
s h_meminfo;  grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo
s h_psi;      for r in cpu memory io; do [ -r /proc/pressure/$r ] && echo "$r $(head -1 /proc/pressure/$r)"; done
netsum(){ awk 'NR>2{gsub(":"," "); if($1!="lo" && $1 !~ /^(veth|docker|br-|vx|cali|flannel)/){rx+=$2;tx+=$10}}END{print rx+0, tx+0}' /proc/net/dev; }
s h_sample_a; head -1 /proc/stat; netsum
sleep 5
s h_sample_b; head -1 /proc/stat; netsum
s h_oci
curl -s -m 3 -H 'Authorization: Bearer Oracle' http://169.254.169.254/opc/v2/instance/ 2>/dev/null | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
c=d.get("shapeConfig") or {}
print(json.dumps({"shape":d.get("shape"),"ocpus":c.get("ocpus"),"memoryInGBs":c.get("memoryInGBs"),
 "bandwidthGbps":c.get("networkingBandwidthInGbps"),"region":d.get("canonicalRegionName") or d.get("region"),
 "timeCreated":d.get("timeCreated")}))' 2>/dev/null
s h_disks;    lsblk -b -d -n -o NAME,SIZE,TYPE 2>/dev/null | awk '$3=="disk"'
s h_fs;       df -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs --output=target,size,used,pcent 2>/dev/null | tail -n +2
s h_reboot;   [ -f /var/run/reboot-required ] && echo yes
s h_failed_units; systemctl --failed --no-legend --plain 2>/dev/null
s h_timers
systemctl list-timers --all --no-legend --plain 2>/dev/null | awk '{print $(NF-1), $NF}' | while read t svc; do
  last=$(date -d "$(systemctl show "$t" -p LastTriggerUSec --value 2>/dev/null)" +%s 2>/dev/null || echo 0)
  echo "$t $svc $(systemctl show "$svc" -p Result --value 2>/dev/null) $(systemctl show "$svc" -p ExecMainStatus --value 2>/dev/null) $last"
done
s h_cron_daemon
a=none; for u in cron crond cronie; do [ "$(systemctl is-active $u 2>/dev/null)" = active ] && a=$u; done
echo "$a $(command -v cron crond 2>/dev/null | head -1)"
s h_cron_jobs; ( crontab -l 2>/dev/null; cat /etc/cron.d/* /var/spool/cron/crontabs/* 2>/dev/null ) | grep -vE '^\s*(#|$|SHELL=|PATH=|MAILTO=)' | grep -v e2scrub | wc -l
s h_oom_count; journalctl -k --since '-30 days' --no-pager 2>/dev/null | grep -ciE 'out of memory|oom-kill|killed process'
s h_oom;      journalctl -k --since '-30 days' --no-pager 2>/dev/null | grep -iE 'out of memory: killed process|oom-kill:' | tail -8
s h_journal_cfg; grep -hE '^\s*SystemMaxUse' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf 2>/dev/null
s h_docker_info; docker info --format '{{.ServerVersion}}|{{.Swarm.LocalNodeState}}|{{.Swarm.ControlAvailable}}|{{.Swarm.Nodes}}|{{.Containers}}|{{.ContainersRunning}}|{{.ContainersStopped}}' 2>/dev/null
s h_task_history; docker info --format '{{json .Swarm.Cluster.Spec.Orchestration}}' 2>/dev/null
s h_containers
docker ps -aq 2>/dev/null | xargs -r docker inspect --format '{{.Name}}|{{.State.Status}}|{{.RestartCount}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.OOMKilled}}|{{.State.ExitCode}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{index .Config.Labels "com.docker.swarm.service.name"}}|{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null
s h_services; docker service ls --format '{{.Name}}|{{.Mode}}|{{.Replicas}}|{{.Image}}' 2>/dev/null
s h_service_tasks
for svc in $(docker service ls --format '{{.Name}}' 2>/dev/null); do
  docker service ps "$svc" --no-trunc --format '{{.CurrentState}}|{{.DesiredState}}|{{.Error}}' 2>/dev/null | sed "s#^#$svc|#"
done
s h_stats;    docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' 2>/dev/null
s h_volumes_top; du -sB1 /var/lib/docker/volumes/*/ 2>/dev/null | sort -rn | head -12
s h_dokploy_image; docker service inspect dokploy --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}' 2>/dev/null
s h_dokploy_du; du -x -B1 --max-depth=2 /etc/dokploy 2>/dev/null | sort -rn | head -15
s h_dokploy_logs
echo "$(find /etc/dokploy/logs -type f 2>/dev/null | wc -l) $(du -sB1 /etc/dokploy/logs 2>/dev/null | cut -f1)"
find /etc/dokploy/logs -type f -mtime +30 -printf '%s\n' 2>/dev/null | awk '{s+=$1;n++}END{print n+0, s+0}'
s h_certs
python3 - <<'PY' 2>/dev/null
import base64, glob, json, subprocess
seen = set()
for p in glob.glob('/etc/dokploy/traefik/dynamic/acme*.json') + glob.glob('/etc/dokploy/traefik/acme*.json'):
    if p in seen: continue
    seen.add(p)
    try: d = json.load(open(p))
    except Exception as e: print(f"ERR|{p}|{e}"); continue
    for resolver, v in (d or {}).items():
        for c in (v or {}).get('Certificates') or []:
            try:
                pem = base64.b64decode(c['certificate'])
                r = subprocess.run(['openssl', 'x509', '-noout', '-enddate'], input=pem, capture_output=True)
                end = r.stdout.decode().strip().split('=', 1)[-1]
                print(f"{c['domain']['main']}|{end}")
            except Exception as e:
                print(f"ERR|{c.get('domain')}|{e}")
PY
s h_traefik_errors
tc=$(docker ps -q --filter name=dokploy-traefik 2>/dev/null | head -1)
if [ -n "$tc" ]; then docker logs --since 72h "$tc" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'unable to obtain|cannot retrieve the acme|acme.*err|err.*acme' | tail -6; fi
s h_backup_dirs
for b in /opt/backups /root/backups /backup /backups /home/*/backups; do
  [ -d "$b" ] || continue
  for d in "$b" $(find "$b" -mindepth 1 -maxdepth 1 -type d 2>/dev/null); do
    n=$(find "$d" -maxdepth 2 -type f 2>/dev/null | sort | head -1)
    [ -n "$n" ] || continue
    echo "$(find "$d" -maxdepth 2 -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1) $d"
  done
done
echo "@@@h_end"
"""

SEV_ORDER = {"CRIT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
DISK_RISK_TO_SEV = {"SAFE": "MEDIUM", "REVIEW": "LOW", "NEVER": "INFO"}
ALWAYS_FREE_BLOCK_GB = 200  # boot + block volumes combined, per tenancy
IDLE_PCT = 20               # OCI idle-reclamation thresholds (CPU p95, network, memory on A1)


# ---------------------------------------------------------------- ssh
def run_remote(args, script: str, timeout: int = 1200) -> str:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if args.key:
        cmd += ["-i", os.path.expanduser(args.key)]
    user = args.host.split("@", 1)[0] if "@" in args.host else ""
    use_sudo = args.sudo == "always" or (args.sudo == "auto" and user != "root")
    cmd += [args.host, "sudo -n bash -s" if use_sudo else "bash -s"]
    # bytes, not text: text mode on Windows turns \n into \r\n and remote bash chokes on it
    r = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True, timeout=timeout)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace").strip()
    if "a password is required" in err:
        sys.exit("sudo needs a password on the remote host; use a root/passwordless-sudo user or --sudo never")
    if r.returncode != 0 and "@@@" not in out:
        sys.exit(f"ssh failed ({r.returncode}): {err[:400]}")
    return out


# ---------------------------------------------------------------- analysis
def _first(sec, key, default=""):
    v = [l for l in sec.get(key, []) if l.strip()]
    return v[0].strip() if v else default


def _cpu_pct(a: str, b: str):
    try:
        x = [int(v) for v in a.split()[1:]]
        y = [int(v) for v in b.split()[1:]]
    except ValueError:
        return None
    idle = (y[3] + y[4]) - (x[3] + x[4])
    total = sum(y) - sum(x)
    return round(100.0 * (total - idle) / total, 1) if total > 0 else None


def _docker_time(s: str):
    if not s or s.startswith("0001"):
        return None
    try:
        return dt.datetime.fromisoformat(s[:19]).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def analyse_health(sec: dict, disk: dict) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    F: list[dict] = []

    def add(area, sev, what, fix="", nbytes=0):
        F.append({"area": area, "severity": sev, "what": what, "fix": fix, "bytes": int(nbytes)})

    ctx: dict = {
        "arch": _first(sec, "h_arch"), "kernel": _first(sec, "h_kernel"), "os": _first(sec, "h_os"),
        "uptime_days": round(float(_first(sec, "h_uptime", "0")) / 86400, 1),
    }

    # --- load / memory / pressure
    nproc = int(_first(sec, "h_nproc", "1") or 1)
    la = _first(sec, "h_loadavg", "0 0 0").split()
    l1, l5, l15 = (float(x) for x in la[:3])
    ctx["load"] = {"1m": l1, "5m": l5, "15m": l15, "cpus": nproc}
    if l15 / nproc > 2:
        add("cpu", "HIGH", f"load15 {l15} on {nproc} CPUs (x{l15 / nproc:.1f})", "find the hot container in the stats table")
    elif l15 / nproc > 1:
        add("cpu", "MEDIUM", f"load15 {l15} on {nproc} CPUs", "watch it; check iowait (PSI io)")

    mi = {}
    for l in sec.get("h_meminfo", []):
        k, v = l.split(":")
        mi[k] = int(v.split()[0]) * 1024
    mt, ma = mi.get("MemTotal", 1), mi.get("MemAvailable", 0)
    st, sf = mi.get("SwapTotal", 0), mi.get("SwapFree", 0)
    mem_used_pct = round(100 * (mt - ma) / mt, 1)
    ctx["memory"] = {"total": mt, "available": ma, "used_pct": mem_used_pct, "swap_total": st, "swap_used": st - sf}
    if ma / mt < 0.05:
        add("memory", "CRIT", f"only {human(ma)} RAM available of {human(mt)}", "OOM killer is next; cap container memory")
    elif ma / mt < 0.10:
        add("memory", "HIGH", f"only {human(ma)} RAM available of {human(mt)}", "cap container memory / move a service")
    if st and (st - sf) / st > 0.5:
        add("memory", "MEDIUM", f"swap {human(st - sf)} of {human(st)} in use", "sustained swapping = RAM too small for the workload")

    psi = {}
    for l in sec.get("h_psi", []):
        r, rest = l.split(None, 1)
        m = re.search(r"avg300=([\d.]+)", rest)
        if m:
            psi[r] = float(m.group(1))
    ctx["psi_avg300"] = psi
    for r, v in psi.items():
        if v > 10:
            add("pressure", "HIGH", f"{r} pressure avg300={v}% (tasks stalled waiting for {r})", "")
        elif v > 2:
            add("pressure", "LOW", f"{r} pressure avg300={v}%", "")

    oomc = int(_first(sec, "h_oom_count", "0") or 0)
    if oomc:
        add("memory", "HIGH", f"{oomc} OOM-killer kernel lines in 30 days; last: "
            + " / ".join(l[-120:] for l in sec.get("h_oom", [])[-3:]),
            "set mem_limit on the offender or add RAM/swap")

    # --- disks / Oracle Always Free
    disks = [(l.split()[0], int(l.split()[1])) for l in sec.get("h_disks", []) if l.strip()]
    ctx["disks"] = disks
    ctx["filesystems"] = sec.get("h_fs", [])
    for l in sec.get("h_fs", []):
        parts = l.split()
        if len(parts) >= 4 and parts[3].endswith("%"):
            p = int(parts[3].rstrip("%"))
            if p >= 90:
                add("disk", "CRIT", f"filesystem {parts[0]} {p}% full", "run the disk section's SAFE items first")
            elif p >= 80:
                add("disk", "HIGH", f"filesystem {parts[0]} {p}% full", "")

    oci = None
    try:
        oci = json.loads(_first(sec, "h_oci", "")) if _first(sec, "h_oci", "") else None
    except ValueError:
        pass
    ctx["oci"] = oci
    a, b = sec.get("h_sample_a", []), sec.get("h_sample_b", [])
    cpu_now = _cpu_pct(a[0], b[0]) if a and b else None
    net_now_mbps = None
    if len(a) > 1 and len(b) > 1:
        ra, ta = map(int, a[1].split())
        rb, tb = map(int, b[1].split())
        net_now_mbps = round(((rb - ra) + (tb - ta)) * 8 / 5 / 1e6, 2)
    ctx["sample_5s"] = {"cpu_pct": cpu_now, "net_mbps": net_now_mbps}
    if oci:
        total_gb = sum(n for _, n in disks) / 2**30  # OCI "GB" for volumes is GiB
        shape = oci.get("shape") or "?"
        ctx["oci"]["attached_disks_gb"] = round(total_gb, 1)
        tc = oci.get("timeCreated")
        if isinstance(tc, (int, float)):
            ctx["oci"]["timeCreated"] = dt.datetime.fromtimestamp(tc / 1000, dt.timezone.utc).date().isoformat()
        if total_gb > ALWAYS_FREE_BLOCK_GB + 0.5:
            add("oracle", "HIGH", f"attached disks total {total_gb:.0f} GB > {ALWAYS_FREE_BLOCK_GB} GB Always Free block "
                "storage (boot + block volumes, whole tenancy)", "you are paying for storage, or will be")
        elif total_gb >= ALWAYS_FREE_BLOCK_GB * 0.95:
            add("oracle", "MEDIUM", f"{shape}: attached disks {total_gb:.0f} GiB = the whole {ALWAYS_FREE_BLOCK_GB} GB "
                "Always Free block-storage budget (boot + block volumes, whole tenancy)",
                "no room for a block volume or boot-volume growth without paying; disk growth must be solved by cleanup")
        else:
            add("oracle", "INFO", f"{shape}: attached disks {total_gb:.0f} GiB of the {ALWAYS_FREE_BLOCK_GB} GB Always Free "
                "block-storage budget (shared by ALL boot+block volumes in the tenancy)",
                "growing the boot volume or adding a block volume must fit this budget")
        a1 = "A1" in shape
        bw = float(oci.get("bandwidthGbps") or 0) * 1000
        idle_bits = []
        if cpu_now is not None:
            idle_bits.append(f"CPU {cpu_now}%")
        idle_bits.append(f"memory {mem_used_pct}%" + (" (counts on A1)" if a1 else ""))
        if net_now_mbps is not None and bw:
            idle_bits.append(f"network {net_now_mbps} Mbps = {100 * net_now_mbps / bw:.2f}% of {bw:.0f} Mbps")
        all_low = (cpu_now or 0) < IDLE_PCT and (net_now_mbps or 0) < 0.2 * (bw or 1e9) and (not a1 or mem_used_pct < IDLE_PCT)
        add("oracle", "HIGH" if all_low else "INFO",
            "idle-reclamation check (Always Free: reclaimed if over 7 days CPU p95 < 20% AND network < 20% "
            f"AND, on A1, memory < 20%). Now: {', '.join(idle_bits)}"
            + (" — ALL below threshold" if all_low else " — at least one metric is above, not idle"),
            "5-second sample only, not the 7-day p95: confirm in OCI Console > Instance > Metrics. "
            "Upgrading the tenancy to Pay-As-You-Go (still free within limits) removes idle reclamation")

    # --- systemd / cron / backups
    for l in sec.get("h_failed_units", []):
        if l.strip():
            add("systemd", "HIGH", f"failed unit: {l.split()[0]}", f"journalctl -u {l.split()[0]} -n 50")
    timers = []
    for l in sec.get("h_timers", []):
        p = l.split()
        if len(p) < 5:
            continue
        t, svc, result, status, last = p[0], p[1], p[2], p[3], int(p[4] or 0)
        age_h = round((now.timestamp() - last) / 3600, 1) if last else None
        timers.append({"timer": t, "service": svc, "result": result, "exit": status, "last_run_h_ago": age_h})
        if result not in ("success", "") or status not in ("0", ""):
            add("timers", "HIGH", f"{t} -> {svc}: last result={result} exit={status}", f"journalctl -u {svc} -n 80")
    ctx["timers"] = timers

    cd = _first(sec, "h_cron_daemon", "none").split()
    njobs = int(_first(sec, "h_cron_jobs", "0") or 0)
    ctx["cron_daemon"] = cd[0] if cd else "none"
    if njobs and ctx["cron_daemon"] == "none":
        add("cron", "HIGH", f"{njobs} cron job lines installed but NO cron daemon is running — they never execute "
            "(including any backup scripts among them)",
            "move each job to a systemd timer (Persistent=true) or install/enable cron; then verify the outputs appear")

    for l in sec.get("h_backup_dirs", []):
        p = l.split(None, 1)
        if len(p) < 2:
            continue
        newest = int(p[0] or 0)
        age_d = (now.timestamp() - newest) / 86400 if newest else 9999
        if age_d > 3:
            add("backups", "HIGH", f"backup dir {p[1]}: newest file is {age_d:.0f} days old", "the job that feeds it is not running")

    if not sec.get("h_journal_cfg"):
        add("journal", "LOW", "journald has no SystemMaxUse (default: 10% of the fs, max 4 GB)",
            "SystemMaxUse=500M in /etc/systemd/journald.conf.d/size.conf")
    if _first(sec, "h_reboot") == "yes":
        add("os", "LOW", "reboot required (kernel/libc update pending)", "schedule a maintenance reboot")

    # --- docker / swarm
    di = _first(sec, "h_docker_info", "").split("|")
    if len(di) >= 7:
        ctx["docker"] = {"version": di[0], "swarm": di[1], "manager": di[2], "nodes": di[3],
                         "containers": di[4], "running": di[5], "stopped": di[6]}
        if di[1] != "active":
            add("swarm", "HIGH", f"Swarm state is `{di[1]}` — Dokploy needs an active swarm", "")
    else:
        add("docker", "CRIT", "docker info returned nothing (daemon down, or no permission)", "")
    th = _first(sec, "h_task_history", "")
    ctx["task_history"] = th

    cont = []
    for l in sec.get("h_containers", []):
        p = l.split("|")
        if len(p) < 10:
            continue
        name, status, rc, health, oom, code, started, finished, svc, policy = p[:10]
        name = name.lstrip("/")
        cont.append({"name": name, "status": status, "restarts": int(rc or 0), "health": health, "oom": oom == "true",
                     "exit": int(code or 0), "service": svc, "policy": policy})
        if status == "restarting":
            add("containers", "CRIT", f"{name} is in a restart loop ({rc} restarts)", f"docker logs --tail 80 {name}")
        if health == "unhealthy":
            add("containers", "HIGH", f"{name} is UNHEALTHY", f"docker inspect --format '{{{{json .State.Health}}}}' {name}")
        if oom == "true":
            add("containers", "HIGH", f"{name} was OOM-killed", "raise/limit its memory deliberately")
        if not svc and int(rc or 0) >= 5 and status == "running":
            add("containers", "MEDIUM", f"{name} restarted {rc} times (running now)", f"docker logs --since 24h {name}")
        if not svc and status == "exited" and int(code or 0) not in (0, 137, 143):
            fin = _docker_time(finished)
            ago = f", {(now - fin).days} days ago" if fin else ""
            add("containers", "MEDIUM", f"{name} exited with code {code}{ago} (not a swarm task)",
                "if it should run: fix and restart; if abandoned: remove it via its PaaS")
    ctx["containers"] = cont
    stopped_tasks = sum(1 for c in cont if c["service"] and c["status"] != "running")
    if stopped_tasks > 20:
        add("swarm", "LOW", f"{stopped_tasks} stopped swarm task containers kept as history ({th})",
            "normal up to TaskHistoryRetentionLimit per slot; lower it with `docker swarm update --task-history-limit 2`")

    services = []
    for l in sec.get("h_services", []):
        p = l.split("|")
        if len(p) < 4:
            continue
        name, mode, rep, image = p[:4]
        m = re.match(r"(\d+)/(\d+)", rep)
        run_, want = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        services.append({"name": name, "mode": mode, "replicas": rep, "image": image})
        if want and run_ == 0:
            add("swarm", "CRIT", f"service {name} has 0/{want} replicas running", f"docker service ps --no-trunc {name}")
        elif run_ < want:
            add("swarm", "HIGH", f"service {name} {run_}/{want} replicas", f"docker service ps --no-trunc {name}")
    ctx["services"] = services
    fails: dict[str, list] = {}
    for l in sec.get("h_service_tasks", []):
        p = l.split("|", 3)
        if len(p) < 4:
            continue
        svc, cur, desired, err = p
        if cur.startswith(("Failed", "Rejected")) or (err and desired == "Shutdown"):
            fails.setdefault(svc, []).append((cur, err))
    for svc, lst in fails.items():
        sev = "HIGH" if len(lst) >= 3 else "MEDIUM"
        add("swarm", sev, f"service {svc}: {len(lst)} failed/rejected tasks in history; latest: "
            f"{lst[0][0]} — {lst[0][1][:160]}", f"docker service ps --no-trunc {svc}")

    stats = []
    for l in sec.get("h_stats", []):
        p = l.split("|")
        if len(p) == 4:
            stats.append({"name": p[0], "cpu": p[1], "mem": p[2], "mem_pct": p[3]})
    stats.sort(key=lambda s: -vpsdisk.parse_size(s["mem"].split("/")[0].replace("iB", "B")))
    ctx["top_mem"] = stats[:12]

    ctx["volumes_top"] = [(int(a), b.rstrip("/").rsplit("/", 1)[-1]) for a, b in
                          (l.split(None, 1) for l in sec.get("h_volumes_top", []) if l.strip())]

    # --- Dokploy itself
    ctx["dokploy_image"] = _first(sec, "h_dokploy_image", "")
    ctx["dokploy_du"] = [(int(a), b) for a, b in (l.split(None, 1) for l in sec.get("h_dokploy_du", []) if l.strip())]
    dl = sec.get("h_dokploy_logs", [])
    if len(dl) >= 2:
        nfiles, lbytes = (dl[0].split() + ["0", "0"])[:2]
        nold, oldbytes = (dl[1].split() + ["0", "0"])[:2]
        ctx["dokploy_logs"] = {"files": int(nfiles or 0), "bytes": int(lbytes or 0), "older_30d_files": int(nold),
                               "older_30d_bytes": int(oldbytes)}
        if int(oldbytes) > 500e6:
            add("dokploy", "LOW", f"/etc/dokploy/logs: {nold} deploy logs older than 30 days = {human(int(oldbytes))}",
                "Dokploy never prunes deploy logs; archive/delete old ones by hand (REVIEW)", int(oldbytes))
    if not ctx["dokploy_image"]:
        add("dokploy", "HIGH", "no `dokploy` swarm service found", "is this a Dokploy host? is the service removed?")

    certs = []
    for l in sec.get("h_certs", []):
        p = l.split("|")
        if p[0] == "ERR":
            add("tls", "MEDIUM", f"could not read cert store: {' '.join(p[1:])[:160]}", "")
            continue
        try:
            end = dt.datetime.strptime(p[1].strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
        except (ValueError, IndexError):
            continue
        days = (end - now).days
        certs.append({"domain": p[0], "expires": end.date().isoformat(), "days": days})
        if days < 0:
            add("tls", "HIGH", f"cert {p[0]} EXPIRED {-days} days ago",
                "if the domain still routes here, renewal is broken; if not, drop the router so Traefik stops retrying")
        elif days < 7:
            add("tls", "CRIT", f"cert {p[0]} expires in {days} days", "check DNS points here + Traefik ACME errors")
        elif days < 25:
            add("tls", "HIGH", f"cert {p[0]} expires in {days} days (LE renews at 30 — renewal is failing)",
                "check DNS points here + Traefik ACME errors")
    certs.sort(key=lambda c: c["days"])
    ctx["certs"] = certs
    terr = [l for l in sec.get("h_traefik_errors", []) if l.strip()]
    if terr:
        doms = sorted(set(re.findall(r"(?:for|domain[s]?[=:]\s*\"?)\s*([a-z0-9.-]+\.[a-z]{2,})", " ".join(terr), re.I)))
        add("tls", "MEDIUM", f"Traefik ACME errors in the last 72h for {', '.join(doms) or '?'} "
            f"(last: {terr[-1][-180:]})",
            "'Cannot retrieve the ACME challenge' = a validation for a token THIS Traefik never issued: "
            "another server is requesting a cert for a name whose DNS points here. Find the duplicate "
            "router; make sure this host's own renewal (30 days before expiry) still succeeds")

    # --- merge the disk report from vps-disk-doctor
    for f in disk["findings"]:
        sev = DISK_RISK_TO_SEV.get(f["risk"], "LOW")
        if f["category"] in ("orphan_volume", "local_backups") and f["bytes"] > 1e9:
            sev = "MEDIUM"  # big + usually still copied by the nightly backup
        add("disk:" + f["category"], sev, f"[{f['risk']}] {f['what']}", f["fix"], f["bytes"])

    F.sort(key=lambda f: (SEV_ORDER[f["severity"]], -f["bytes"]))
    return {"host": disk["host"], "scanned_at": disk["scanned_at"], "findings": F, "context": ctx, "disk": disk}


# ---------------------------------------------------------------- output
def to_markdown(rep: dict) -> str:
    c, d = rep["context"], rep["disk"]
    m = c["memory"]
    out = [f"# Dokploy host health — {rep['host']} ({rep['scanned_at']})", "",
           f"{c['os']} · {c['arch']} · kernel {c['kernel']} · up {c['uptime_days']} d · "
           f"docker {c.get('docker', {}).get('version', '?')} · swarm {c.get('docker', {}).get('swarm', '?')} · "
           f"Dokploy image `{c.get('dokploy_image') or '?'}`", "",
           f"- **Disk /** {d['disk']['pct']}% ({human(d['disk']['used'])} / {human(d['disk']['size'])}), "
           f"SAFE reclaimable {human(d['safe_reclaimable'])}",
           f"- **RAM** {m['used_pct']}% used, {human(m['available'])} available of {human(m['total'])}; "
           f"swap {human(m['swap_used'])} / {human(m['swap_total'])}",
           f"- **Load** {c['load']['1m']} / {c['load']['5m']} / {c['load']['15m']} on {c['load']['cpus']} CPUs; "
           f"PSI avg300 {c['psi_avg300']}; 5 s sample CPU {c['sample_5s']['cpu_pct']}%, net {c['sample_5s']['net_mbps']} Mbps"]
    if c.get("oci"):
        o = c["oci"]
        out.append(f"- **Oracle** {o.get('shape')} {o.get('ocpus')} OCPU / {o.get('memoryInGBs')} GB, "
                   f"disks {o.get('attached_disks_gb')} GB, created {str(o.get('timeCreated'))[:10]}")
    counts = {}
    for f in rep["findings"]:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    out += ["", "## Findings", "", " · ".join(f"{k} {counts[k]}" for k in SEV_ORDER if k in counts), "",
            "| Sev | Area | Size | What | Fix |", "|---|---|---:|---|---|"]
    for f in rep["findings"]:
        size = human(f["bytes"]) if f["bytes"] else ""
        out.append(f"| {f['severity']} | {f['area']} | {size} | {f['what']} | {f['fix']} |")
    if c.get("services"):
        out += ["", "## Swarm services", "", "| Service | Replicas | Image |", "|---|---|---|"]
        out += [f"| {s['name']} | {s['replicas']} | `{s['image'][:70]}` |" for s in c["services"]]
    if c.get("top_mem"):
        out += ["", "## Top containers by memory", "", "| Container | CPU | Mem | Mem% |", "|---|---:|---:|---:|"]
        out += [f"| {s['name'][:60]} | {s['cpu']} | {s['mem']} | {s['mem_pct']} |" for s in c["top_mem"]]
    if c.get("certs"):
        out += ["", "## TLS certificates (Traefik acme)", "", "| Domain | Expires | Days |", "|---|---|---:|"]
        out += [f"| {x['domain']} | {x['expires']} | {x['days']} |" for x in c["certs"]]
    if c.get("timers"):
        out += ["", "## systemd timers", "", "| Timer | Result | Exit | Last run (h ago) |", "|---|---|---:|---:|"]
        out += [f"| {t['timer']} | {t['result']} | {t['exit']} | {t['last_run_h_ago']} |" for t in c["timers"]]
    out += ["", f"cron daemon: **{c['cron_daemon']}** · swarm task history: `{c.get('task_history')}`"]
    if c.get("volumes_top"):
        out += ["", "## Biggest docker volumes", "", "| Size | Volume |", "|---:|---|"]
        out += [f"| {human(n)} | `{v}` |" for n, v in c["volumes_top"]]
    if c.get("dokploy_du"):
        out += ["", "## /etc/dokploy", "", "| Size | Path |", "|---:|---|"]
        out += [f"| {human(n)} | `{p}` |" for n, p in c["dokploy_du"][:10]]
    out += ["", "---", "", vpsdisk.to_markdown(d).replace("# Disk report", "## Disk detail (vps-disk-doctor)")]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- commands
def cmd_report(args):
    raw = run_remote(args, vpsdisk.PROBE + "\n" + HEALTH)
    sec = vpsdisk.sections(raw)
    rep = analyse_health(sec, vpsdisk.analyse(sec))
    md = to_markdown(rep)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, ensure_ascii=False, default=str)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(md)
    sys.stdout.reconfigure(encoding="utf-8")
    print(md)


def cmd_clean(args):
    actions = vpsdisk.CLEAN_ACTIONS  # the SAFE-only whitelist lives in ONE place
    keys = [k.strip() for k in args.only.split(",") if k.strip()]
    bad = [k for k in keys if k not in actions]
    if not keys or bad:
        sys.exit(f"refusing: {bad or 'nothing'} — allowed SAFE actions: {', '.join(actions)}")
    print("Plan:")
    for k in keys:
        risk, what, command = actions[k]
        print(f"  [{risk}] {k:9} {what}\n            $ {command}")
    remote_host = run_remote(args, "hostname").strip()
    if not args.armed:
        print(f"\nDry run on {remote_host}. Re-run with --armed --confirm {remote_host} to execute.")
        return
    if args.confirm != remote_host:
        sys.exit(f"refusing: --confirm must equal the remote hostname ({remote_host!r}).")
    body = ["set -u", "echo BEFORE; df -h / | tail -1"]
    for k in keys:
        body += [f"echo '== {k}'", actions[k][2] + " 2>&1 | tail -3"]
    body += ["echo AFTER; df -h / | tail -1",
             f"echo \"$(date -Is) dokploy-doctor clean {','.join(keys)}\" >> /var/log/vps-disk-doctor.log"]
    print(run_remote(args, "\n".join(body)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("DOKDOC_HOST") or os.environ.get("VPSDISK_HOST"),
                    help="user@host or an ssh alias")
    ap.add_argument("-i", "--key", default=os.environ.get("DOKDOC_KEY") or os.environ.get("VPSDISK_KEY"),
                    help="ssh private key")
    ap.add_argument("--sudo", choices=["auto", "always", "never"], default="auto",
                    help="run the remote script under sudo -n (auto: unless user is root)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="read-only health report (one ssh session)")
    rp.add_argument("--json")
    rp.add_argument("--markdown")
    cl = sub.add_parser("clean", help="SAFE-only removal via vps-disk-doctor's whitelist; dry run unless --armed")
    cl.add_argument("--only", required=True, help=",".join(vpsdisk.CLEAN_ACTIONS))
    cl.add_argument("--armed", action="store_true")
    cl.add_argument("--confirm", help="must equal the remote hostname")
    args = ap.parse_args()
    if not args.host:
        sys.exit("--host (or DOKDOC_HOST) is required")
    {"report": cmd_report, "clean": cmd_clean}[args.cmd](args)


if __name__ == "__main__":
    main()
