#!/usr/bin/env python3
"""Guardian — VPS backup daemon (cron-driven).

Backs up EVERY meaningful docker volume on the host (app data + PaaS control-plane),
keeps ONE local copy, and pushes each volume to a PRIVATE Backblaze B2 bucket with a
rolling 3-daily + 3-weekly retention. Sends a WhatsApp report when done.

Self-contained: only needs python3 + boto3 + docker. Config lives in
/etc/guardian/config.json (see config.example.json). No repo / uv dependency, so it
survives on a bare VPS via cron.

Companion: restore_guardian.py rebuilds volumes from B2 on a fresh machine (DR).

  backup_guardian.py            # run a backup (what cron calls)
  backup_guardian.py test       # send a WhatsApp test message
  backup_guardian.py list       # show resolved config + volumes that WOULD be backed up
  backup_guardian.py check      # B2 connectivity + docker reachability
  backup_guardian.py stats      # local + B2 backup inventory
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, time
from datetime import datetime, timezone

CONFIG_PATH = os.environ.get("GUARDIAN_CONFIG", "/etc/guardian/config.json")

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"Missing config: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("backup_dir", "/root/backups")
    cfg.setdefault("local_keep", 1)
    cfg.setdefault("exclude_patterns", [r"^[0-9a-f]{64}$", "redis"])
    cfg.setdefault("weekly_weekday", 5)          # Mon=0 .. Sun=6 ; Saturday=5
    cfg.setdefault("b2_daily_keep", 3)
    cfg.setdefault("b2_weekly_keep", 3)
    cfg.setdefault("tar_timeout", 1800)
    if not cfg.get("host_label"):
        sys.exit("config.host_label is required (e.g. 'coolify' / 'oracle')")
    b2 = cfg.get("b2", {})
    if not b2.get("endpoint") and b2.get("region"):
        b2["endpoint"] = f"https://s3.{b2['region']}.backblazeb2.com"
    cfg["b2"] = b2
    return cfg


# ----------------------------------------------------------------------------- B2
def b2_client(b2: dict):
    import boto3
    miss = [k for k in ("endpoint", "key_id", "application_key", "bucket") if not b2.get(k)]
    if miss:
        raise RuntimeError(f"B2 config missing: {', '.join(miss)}")
    return boto3.client(
        "s3", endpoint_url=b2["endpoint"], aws_access_key_id=b2["key_id"],
        aws_secret_access_key=b2["application_key"], region_name=b2.get("region", "us-east-005"))


def b2_upload(s3, bucket: str, key: str, path: str) -> None:
    s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": "application/gzip"})


def b2_prune(s3, bucket: str, prefix: str, keep: int) -> int:
    """Keep newest `keep` objects under prefix (by key name = date-sortable). Delete rest."""
    keys = []
    pag = s3.get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            keys.append(o["Key"])
    keys.sort(reverse=True)
    doomed = keys[keep:]
    for k in doomed:
        s3.delete_object(Bucket=bucket, Key=k)
    return len(doomed)


# ------------------------------------------------------------------------- docker
def list_volumes() -> list[str]:
    out = subprocess.run(["docker", "volume", "ls", "--format", "{{.Name}}"],
                         capture_output=True, text=True, timeout=30)
    return [v for v in out.stdout.splitlines() if v.strip()]


def select_volumes(cfg: dict) -> list[str]:
    pats = [re.compile(p, re.IGNORECASE) for p in cfg["exclude_patterns"]]
    keep = []
    for v in list_volumes():
        if any(p.search(v) for p in pats):
            continue
        keep.append(v)
    return sorted(keep)


def human(nbytes: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if nbytes >= div:
            return f"{nbytes / div:.1f}{unit}"
    return f"{nbytes}B"


def tar_volume(volume: str, dest_dir: str, timeout: int) -> tuple[bool, str, int]:
    """tar.gz a docker volume into dest_dir via a throwaway alpine container."""
    safe = volume.replace("/", "_").replace("\\", "_")
    out_file = os.path.join(dest_dir, f"{safe}.tar.gz")
    cmd = ["docker", "run", "--rm",
           "-v", f"{volume}:/data:ro",
           "-v", f"{dest_dir}:/backup",
           "alpine", "tar", "czf", f"/backup/{safe}.tar.gz", "-C", "/data", "."]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0 and os.path.exists(out_file):
        return True, out_file, os.path.getsize(out_file)
    log(f"  tar FAIL {volume}: {r.stderr.strip()[:200]}")
    return False, out_file, 0


# ------------------------------------------------------------------------ whatsapp
def send_whatsapp(cfg: dict, message: str) -> bool:
    wa = cfg.get("whatsapp")
    if not wa or not wa.get("api_url"):
        log("WhatsApp not configured; skipping notify")
        return False
    try:
        import urllib.request
        url = f"{wa['api_url']}/message/sendText/{wa['instance']}"
        data = json.dumps({"number": wa["target_number"], "text": message}).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "apikey": wa["api_key"]})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (200, 201)
            log(f"WhatsApp {'OK' if ok else resp.status}")
            return ok
    except Exception as e:
        log(f"WhatsApp error: {e}")
        return False


# ---------------------------------------------------------------------------- run
def run_backup(cfg: dict) -> int:
    host = cfg["host_label"]
    now = datetime.now()
    date_tag = now.strftime("%Y%m%d")
    ts = now.strftime("%Y%m%d_%H%M%S")
    is_weekly = now.weekday() == int(cfg["weekly_weekday"])
    backup_dir = cfg["backup_dir"]
    folder = os.path.join(backup_dir, ts)
    os.makedirs(folder, exist_ok=True)
    log(f"=== GUARDIAN BACKUP {host} {ts} (weekly={is_weekly}) ===")

    vols = select_volumes(cfg)
    log(f"{len(vols)} volumes selected: {', '.join(vols)}")

    # B2 client (optional — local backup still proceeds if B2 down)
    s3 = None
    try:
        s3 = b2_client(cfg["b2"])
    except Exception as e:
        log(f"B2 unavailable ({e}); local backup only")

    items, manifest = {}, {}
    start = time.time()
    for v in vols:
        log(f"backing up {v} ...")
        ok, path, size = tar_volume(v, folder, cfg["tar_timeout"])
        rec = {"status": "OK" if ok else "FAIL", "size": human(size), "bytes": size}
        b2_status = "skip"
        if ok and s3:
            daily_key = f"guardian/{host}/{v}/daily/{date_tag}.tar.gz"
            try:
                b2_upload(s3, cfg["b2"]["bucket"], daily_key, path)
                b2_prune(s3, cfg["b2"]["bucket"], f"guardian/{host}/{v}/daily/", cfg["b2_daily_keep"])
                manifest[v] = {"daily": daily_key}
                b2_status = "daily"
                if is_weekly:
                    weekly_key = f"guardian/{host}/{v}/weekly/{date_tag}.tar.gz"
                    s3.copy_object(Bucket=cfg["b2"]["bucket"],
                                   CopySource={"Bucket": cfg["b2"]["bucket"], "Key": daily_key},
                                   Key=weekly_key)
                    b2_prune(s3, cfg["b2"]["bucket"], f"guardian/{host}/{v}/weekly/", cfg["b2_weekly_keep"])
                    manifest[v]["weekly"] = weekly_key
                    b2_status = "daily+weekly"
            except Exception as e:
                log(f"  B2 upload FAIL {v}: {e}")
                b2_status = "B2-FAIL"
        rec["b2"] = b2_status
        items[v] = rec
        log(f"  {v}: {rec['status']} {rec['size']} [{b2_status}]")

    dur = int(time.time() - start)
    ok_count = sum(1 for r in items.values() if r["status"] == "OK")
    b2_ok = sum(1 for r in items.values() if r["b2"].startswith("daily"))
    total_bytes = sum(r["bytes"] for r in items.values())
    status = "success" if ok_count == len(items) and (not s3 or b2_ok == ok_count) else "partial"

    info = {"host": host, "timestamp": ts, "weekly": is_weekly, "status": status,
            "duration": f"{dur//60}min {dur%60}s", "total_size": human(total_bytes),
            "items": items}
    with open(os.path.join(folder, "backup_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    # upload manifest (what restore reads) + LATEST pointer
    if s3 and manifest:
        try:
            man = {"host": host, "date": date_tag, "ts": ts,
                   "generated": datetime.now(timezone.utc).isoformat(), "volumes": manifest}
            body = json.dumps(man, indent=2).encode()
            for key in (f"guardian/{host}/manifests/{date_tag}.json",
                        f"guardian/{host}/LATEST.json"):
                s3.put_object(Bucket=cfg["b2"]["bucket"], Key=key, Body=body,
                              ContentType="application/json")
            b2_prune(s3, cfg["b2"]["bucket"], f"guardian/{host}/manifests/",
                     max(cfg["b2_daily_keep"], cfg["b2_weekly_keep"]) + 1)
        except Exception as e:
            log(f"manifest upload FAIL: {e}")

    cleanup_local(cfg)
    report = format_report(cfg, info, s3 is not None)
    send_whatsapp(cfg, report)
    log(f"=== DONE {status} {ok_count}/{len(items)} vols, B2 {b2_ok}/{ok_count}, {info['total_size']} in {info['duration']} ===")
    return 0 if status == "success" else 1


def cleanup_local(cfg: dict) -> int:
    bd = cfg["backup_dir"]
    keep = int(cfg["local_keep"])
    dirs = sorted([d for d in os.listdir(bd)
                   if os.path.isdir(os.path.join(bd, d)) and d.replace("_", "").isdigit()],
                  reverse=True)
    removed = 0
    for d in dirs[keep:]:
        try:
            shutil.rmtree(os.path.join(bd, d)); removed += 1
            log(f"pruned local backup {d}")
        except Exception as e:
            log(f"prune FAIL {d}: {e}")
    return removed


def format_report(cfg: dict, info: dict, b2_on: bool) -> str:
    emoji = "✅" if info["status"] == "success" else "⚠️"
    head = "SUCESSO" if info["status"] == "success" else "PARCIAL"
    ok = sum(1 for r in info["items"].values() if r["status"] == "OK")
    msg = (f"🛡️ GUARDIAN BACKUP [{cfg['host_label']}] {emoji}\n\n"
           f"📊 {head} — {ok}/{len(info['items'])} volumes\n"
           f"💾 {info['total_size']} em {info['duration']}\n"
           f"☁️ Backblaze: {'ON (3 diários + 3 semanais)' if b2_on else 'OFF'}"
           f"{' • semana ✓' if info['weekly'] else ''}\n"
           f"📁 Local: {cfg['local_keep']} cópia\n\n📦 VOLUMES:")
    for name, r in info["items"].items():
        mk = "✓" if r["status"] == "OK" else "✗"
        b2m = {"daily": "☁️", "daily+weekly": "☁️📅", "B2-FAIL": "⚠️☁️", "skip": "·"}.get(r["b2"], "·")
        msg += f"\n{mk} {name}: {r['size']} {b2m}"
    msg += f"\n\n{datetime.now().strftime('%d/%m/%Y %H:%M')}"
    return msg


# --------------------------------------------------------------------------- cli
def cmd_list(cfg):
    vols = select_volumes(cfg)
    print(f"\nhost_label : {cfg['host_label']}")
    print(f"backup_dir : {cfg['backup_dir']}  (keep {cfg['local_keep']})")
    print(f"weekly day : {cfg['weekly_weekday']} (Mon=0..Sun=6)  B2 keep {cfg['b2_daily_keep']}d/{cfg['b2_weekly_keep']}w")
    print(f"excludes   : {cfg['exclude_patterns']}")
    print(f"\nvolumes to back up ({len(vols)}):")
    for v in vols: print(f"  - {v}")
    print()


def cmd_check(cfg):
    try:
        n = len(list_volumes()); print(f"docker OK — {n} volumes visible")
    except Exception as e:
        print(f"docker FAIL: {e}")
    try:
        s3 = b2_client(cfg["b2"]); s3.head_bucket(Bucket=cfg["b2"]["bucket"])
        print(f"B2 OK — bucket {cfg['b2']['bucket']} @ {cfg['b2']['endpoint']}")
    except Exception as e:
        print(f"B2 FAIL: {e}")


def cmd_stats(cfg):
    bd = cfg["backup_dir"]
    if os.path.isdir(bd):
        dirs = [d for d in os.listdir(bd) if os.path.isdir(os.path.join(bd, d))]
        print(f"local: {len(dirs)} backup(s) in {bd}: {', '.join(sorted(dirs)) or '—'}")
    try:
        s3 = b2_client(cfg["b2"]); host = cfg["host_label"]
        pag = s3.get_paginator("list_objects_v2"); n = tot = 0
        for page in pag.paginate(Bucket=cfg["b2"]["bucket"], Prefix=f"guardian/{host}/"):
            for o in page.get("Contents", []):
                n += 1; tot += o["Size"]
        print(f"B2 guardian/{host}/: {n} objects, {human(tot)}")
    except Exception as e:
        print(f"B2 stats FAIL: {e}")


def main():
    cfg = load_config()
    arg = sys.argv[1] if len(sys.argv) > 1 else "run"
    if arg == "test":
        sys.exit(0 if send_whatsapp(cfg, "🧪 Guardian backup — teste OK") else 1)
    if arg == "list":  cmd_list(cfg);  return
    if arg == "check": cmd_check(cfg); return
    if arg == "stats": cmd_stats(cfg); return
    if arg == "run":   sys.exit(run_backup(cfg))
    sys.exit(f"unknown command: {arg}")


if __name__ == "__main__":
    main()
