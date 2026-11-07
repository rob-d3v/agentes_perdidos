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
    # Objects bigger than this are NOT weekly-copied server-side (see b2_weekly_snapshot).
    cfg.setdefault("weekly_copy_max_bytes", 512 * 1024 * 1024)
    # Lifecycle safety net: how long a superseded (noncurrent) version may survive.
    cfg.setdefault("b2_noncurrent_days", 7)
    if not cfg.get("host_label"):
        sys.exit("config.host_label is required (e.g. 'coolify' / 'oracle')")
    b2 = cfg.get("b2", {})
    if not b2.get("endpoint") and b2.get("region"):
        b2["endpoint"] = f"https://s3.{b2['region']}.backblazeb2.com"
    # Transport tuning — see b2_client() for why the botocore defaults burn money here.
    b2.setdefault("connect_timeout", 30)
    b2.setdefault("read_timeout", 900)
    b2.setdefault("max_attempts", 3)
    cfg["b2"] = b2
    return cfg


# ----------------------------------------------------------------------------- B2
def b2_client(b2: dict):
    """boto3 S3 client tuned for B2.

    The botocore defaults are actively harmful here: read_timeout=60s is far below the
    time B2 needs to finish a server-side copy of a multi-GB object, and the legacy
    retry mode then retries that *non-idempotent* copy up to 5 times. B2 completes
    every attempt, so one timed-out weekly copy left 5 identical GB-sized versions in a
    versioned bucket while the run was still reported as a failure. Generous timeouts +
    `standard` retry mode (retries only genuinely retryable errors) fix that.
    """
    import boto3
    from botocore.config import Config
    miss = [k for k in ("endpoint", "key_id", "application_key", "bucket") if not b2.get(k)]
    if miss:
        raise RuntimeError(f"B2 config missing: {', '.join(miss)}")
    conf = Config(
        signature_version="s3v4",
        connect_timeout=int(b2.get("connect_timeout", 30)),
        read_timeout=int(b2.get("read_timeout", 900)),
        retries={"max_attempts": int(b2.get("max_attempts", 3)), "mode": "standard"},
    )
    return boto3.client(
        "s3", endpoint_url=b2["endpoint"], aws_access_key_id=b2["key_id"],
        aws_secret_access_key=b2["application_key"],
        region_name=b2.get("region", "us-east-005"), config=conf)


def b2_upload(s3, bucket: str, key: str, path: str) -> None:
    s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": "application/gzip"})


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _version_ts(v: dict):
    lm = v.get("LastModified")
    return lm if lm is not None else _EPOCH


def _list_versions(s3, bucket: str, prefix: str) -> dict[str, list[dict]]:
    """key -> every stored entry for it: real versions AND delete markers."""
    out: dict[str, list[dict]] = {}
    pag = s3.get_paginator("list_object_versions")
    for page in pag.paginate(Bucket=bucket, Prefix=prefix):
        for kind in ("Versions", "DeleteMarkers"):
            for o in page.get(kind, []):
                out.setdefault(o["Key"], []).append({
                    "VersionId": o.get("VersionId") or "null",
                    "IsLatest": bool(o.get("IsLatest")),
                    "LastModified": o.get("LastModified"),
                    "Size": int(o.get("Size", 0)),
                    "marker": kind == "DeleteMarkers",
                })
    return out


def _delete_versions(s3, bucket: str, doomed: list[dict]) -> int:
    """Hard-delete explicit {Key, VersionId} entries, batched 1000 per API call."""
    deleted = 0
    for i in range(0, len(doomed), 1000):
        chunk = doomed[i:i + 1000]
        resp = s3.delete_objects(Bucket=bucket, Delete={"Objects": chunk, "Quiet": True})
        errs = resp.get("Errors") or []
        for e in errs[:5]:
            log(f"  version delete FAIL {e.get('Key')}: {e.get('Code')} {e.get('Message')}")
        if len(errs) > 5:
            log(f"  ... {len(errs) - 5} more version delete errors")
        deleted += len(chunk) - len(errs)
    return deleted


def b2_prune(s3, bucket: str, prefix: str, keep: int) -> int:
    """Keep the newest `keep` keys under prefix (by key name = date-sortable) and, for
    each survivor, keep ONLY its current version.

    The bucket has versioning Enabled: `delete_object(Bucket, Key)` merely writes a
    delete marker, so the old bytes are billed forever (that is how 520 GB of garbage
    accumulated). Everything here deletes explicit VersionIds — old versions, redundant
    duplicates of a surviving key, and stale delete markers — batched via delete_objects.
    Per-key deduplication is folded in here (rather than being a separate pass) so one
    listing serves both jobs; b2_dedupe_versions() exposes it for prefixes that are not
    subject to `keep` retention, e.g. the daily-rewritten LATEST.json.

    Returns the number of KEYS pruned, keeping the return contract callers already use.
    """
    by_key = _list_versions(s3, bucket, prefix)
    if not by_key:
        return 0
    # A key holding nothing but delete markers is already logically gone: it is garbage to
    # purge, but it must not consume one of the `keep` retention slots.
    live = sorted([k for k, vs in by_key.items() if any(not v["marker"] for v in vs)], reverse=True)
    survivors = set(live[:keep])
    doomed: list[dict] = []
    extra = 0                     # superseded versions/markers of keys we are keeping
    freed = 0                     # bytes actually reclaimed (markers are 0-byte)
    for key, vers in sorted(by_key.items()):
        keeper = None
        if key in survivors:
            keeper = next((v for v in vers if v["IsLatest"] and not v["marker"]), None)
            if keeper is None:    # latest is a delete marker -> fall back to newest real version
                keeper = max((v for v in vers if not v["marker"]), key=_version_ts)
        for v in vers:
            if v is keeper:
                continue
            doomed.append({"Key": key, "VersionId": v["VersionId"]})
            freed += v["Size"]
            if keeper is not None:
                extra += 1
    if not doomed:
        return 0
    _delete_versions(s3, bucket, doomed)
    pruned_keys = len(by_key) - len(survivors)
    log(f"  prune {prefix}: {pruned_keys} key(s) + {extra} stale version(s)/marker(s), "
        f"{human(freed)} freed")
    return pruned_keys


def b2_dedupe_versions(s3, bucket: str, prefix: str) -> int:
    """Keep only the current (IsLatest) version of every key under prefix; hard-delete
    the rest, delete markers included. Cheap insurance against duplicate versions of the
    same key (retried uploads/copies) on prefixes b2_prune does not cover."""
    by_key = _list_versions(s3, bucket, prefix)
    doomed: list[dict] = []
    for key, vers in by_key.items():
        keeper = next((v for v in vers if v["IsLatest"] and not v["marker"]), None)
        for v in vers:
            if v is not keeper:
                doomed.append({"Key": key, "VersionId": v["VersionId"]})
    if not doomed:
        return 0
    n = _delete_versions(s3, bucket, doomed)
    log(f"  dedupe {prefix}: {n} redundant version(s)/marker(s) purged")
    return n


def b2_ensure_lifecycle(s3, bucket: str, noncurrent_days: int = 7) -> bool:
    """Idempotently install the safety-net lifecycle rule, so a failed prune can no longer
    grow the bill unbounded.

    Deliberately MINIMAL — exactly the shape B2 accepts (verified against the live
    bucket). On B2 `NoncurrentVersionExpiration` maps to the native
    `daysFromHidingToDeleting`, which also reaps the delete markers, so this single rule
    covers both stale versions and stale markers.

    Do NOT add `Expiration: {"ExpiredObjectDeleteMarker": True}`: B2 rejects it with
    `MalformedXML ... has an ExpiredObjectDeleteMarker rule but there is no Expiration
    rule with the exact same prefix`, and the Expiration rule it demands (empty prefix)
    would delete the CURRENT backups. Same reason there is no
    AbortIncompleteMultipartUpload here: unneeded for the fix, one more way to get the
    whole configuration rejected.

    A rejection is logged loudly (apply by hand in the Backblaze console) and is never
    fatal to the backup.
    """
    rule = {
        "ID": "guardian-expire-noncurrent",
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "NoncurrentVersionExpiration": {"NoncurrentDays": int(noncurrent_days)},
    }
    try:
        current = s3.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except Exception:
        current = []              # no configuration yet (B2 404s) — treat as empty
    for r in current:
        if (r.get("ID") == rule["ID"] and r.get("Status") == "Enabled"
                and r.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays")
                == rule["NoncurrentVersionExpiration"]["NoncurrentDays"]):
            return True           # already in place — nothing to do
    keep_rules = [r for r in current if r.get("ID") != rule["ID"]]
    try:
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket, LifecycleConfiguration={"Rules": keep_rules + [rule]})
    except Exception as e:
        log(f"lifecycle NOT applied on {bucket}: {e}")
        log(f"  -> set it manually in the Backblaze console (Lifecycle Settings): "
            f"'Keep only the last version', hide/delete after {noncurrent_days} day(s)")
        return False
    log(f"lifecycle applied on {bucket}: noncurrent versions expire in {noncurrent_days}d "
        f"(delete markers reaped with them)")
    return True


def b2_weekly_snapshot(s3, bucket: str, daily_key: str, weekly_key: str,
                       path: str, size: int, copy_max_bytes: int) -> str:
    """Materialise the weekly snapshot and return how it was done ('copy' | 'upload').

    Server-side copy_object is free and instant for small objects, but B2 takes minutes
    on multi-GB ones; when the client gives up first, botocore retries a non-idempotent
    copy that B2 finishes anyway, leaving several identical GB-sized versions behind.
    Above the threshold we therefore re-upload the local tarball, which is still on disk
    at this point in run_backup(): a multipart PUT to a fixed key is safe to retry and
    can never produce more than one extra version.
    """
    if size > copy_max_bytes and path and os.path.exists(path):
        b2_upload(s3, bucket, weekly_key, path)
        return "upload"
    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": daily_key},
                   Key=weekly_key)
    return "copy"


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
    # Free room BEFORE staging: otherwise the disk peaks at previous + current set during
    # the run. Only sets already fully in B2 (.b2_ok) go; the new one takes the last slot.
    if os.path.isdir(backup_dir):
        cleanup_local(cfg, keep=max(int(cfg["local_keep"]) - 1, 0), only_b2_ok=True)
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
    if s3:
        # Safety net in case a prune ever fails again — never fatal to the backup.
        try:
            b2_ensure_lifecycle(s3, cfg["b2"]["bucket"], int(cfg["b2_noncurrent_days"]))
        except Exception as e:
            log(f"lifecycle check FAIL (ignored): {e}")

    items, manifest = {}, {}
    start = time.time()
    for v in vols:
        log(f"backing up {v} ...")
        ok, path, size = tar_volume(v, folder, cfg["tar_timeout"])
        rec = {"status": "OK" if ok else "FAIL", "size": human(size), "bytes": size}
        b2_status = "skip"
        if ok and s3:
            bucket = cfg["b2"]["bucket"]
            daily_key = f"guardian/{host}/{v}/daily/{date_tag}.tar.gz"
            try:
                b2_upload(s3, bucket, daily_key, path)
                b2_prune(s3, bucket, f"guardian/{host}/{v}/daily/", cfg["b2_daily_keep"])
                manifest[v] = {"daily": daily_key}
                b2_status = "daily"
            except Exception as e:
                log(f"  B2 daily upload FAIL {v}: {e}")
                b2_status = "B2-FAIL"
            # The weekly snapshot is a separate failure domain: a daily that landed is a
            # usable backup, so a weekly hiccup must not mark the whole volume B2-FAIL.
            if b2_status == "daily" and is_weekly:
                weekly_key = f"guardian/{host}/{v}/weekly/{date_tag}.tar.gz"
                try:
                    how = b2_weekly_snapshot(s3, bucket, daily_key, weekly_key, path, size,
                                             int(cfg["weekly_copy_max_bytes"]))
                    b2_prune(s3, bucket, f"guardian/{host}/{v}/weekly/", cfg["b2_weekly_keep"])
                    manifest[v]["weekly"] = weekly_key
                    b2_status = "daily+weekly"
                    log(f"  weekly via {how}: {weekly_key}")
                except Exception as e:
                    log(f"  B2 weekly FAIL {v} (daily OK): {e}")
                    # Drop any duplicate version a retried/aborted attempt may have left.
                    try:
                        b2_dedupe_versions(s3, bucket, weekly_key)
                    except Exception as de:
                        log(f"  weekly dedupe FAIL {v}: {de}")
                    b2_status = "daily+weekly-FAIL"
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
            # LATEST.json is rewritten every run and has no `keep` retention, so it only
            # ever needs its current version — otherwise it collects one version per day.
            b2_dedupe_versions(s3, cfg["b2"]["bucket"], f"guardian/{host}/LATEST.json")
        except Exception as e:
            log(f"manifest upload FAIL: {e}")

    if s3 and ok_count and b2_ok == ok_count:
        open(os.path.join(folder, ".b2_ok"), "w").close()
    # local_keep 0 = "only in B2": never drop a set that did not fully land there.
    cleanup_local(cfg, only_b2_ok=int(cfg["local_keep"]) == 0)
    report = format_report(cfg, info, s3 is not None)
    send_whatsapp(cfg, report)
    log(f"=== DONE {status} {ok_count}/{len(items)} vols, B2 {b2_ok}/{ok_count}, {info['total_size']} in {info['duration']} ===")
    return 0 if status == "success" else 1


def cleanup_local(cfg: dict, keep: int | None = None, only_b2_ok: bool = False) -> int:
    bd = cfg["backup_dir"]
    keep = int(cfg["local_keep"]) if keep is None else keep
    dirs = sorted([d for d in os.listdir(bd)
                   if os.path.isdir(os.path.join(bd, d)) and d.replace("_", "").isdigit()],
                  reverse=True)
    removed = 0
    for d in dirs[keep:]:
        if only_b2_ok and not os.path.exists(os.path.join(bd, d, ".b2_ok")):
            continue  # not proven in B2 yet — it may be the only copy
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
    week_fail = sum(1 for r in info["items"].values() if r["b2"] == "daily+weekly-FAIL")
    week_mark = ""
    if info["weekly"]:
        week_mark = f" • semana ⚠️ ({week_fail})" if week_fail else " • semana ✓"
    msg = (f"🛡️ GUARDIAN BACKUP [{cfg['host_label']}] {emoji}\n\n"
           f"📊 {head} — {ok}/{len(info['items'])} volumes\n"
           f"💾 {info['total_size']} em {info['duration']}\n"
           f"☁️ Backblaze: {'ON (3 diários + 3 semanais)' if b2_on else 'OFF'}"
           f"{week_mark}\n"
           f"📁 Local: {cfg['local_keep']} cópia\n\n📦 VOLUMES:")
    for name, r in info["items"].items():
        mk = "✓" if r["status"] == "OK" else "✗"
        b2m = {"daily": "☁️", "daily+weekly": "☁️📅", "daily+weekly-FAIL": "☁️⚠️📅",
               "B2-FAIL": "⚠️☁️", "skip": "·"}.get(r["b2"], "·")
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
    print(f"weekly copy: server-side up to {human(int(cfg['weekly_copy_max_bytes']))}, "
          f"re-upload above it   lifecycle: noncurrent {cfg['b2_noncurrent_days']}d")
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
        # Versioned bucket: current objects are only part of the bill.
        vpag = s3.get_paginator("list_object_versions"); old = oldb = marks = 0
        for page in vpag.paginate(Bucket=cfg["b2"]["bucket"], Prefix=f"guardian/{host}/"):
            for o in page.get("Versions", []):
                if not o.get("IsLatest"):
                    old += 1; oldb += int(o.get("Size", 0))
            marks += len(page.get("DeleteMarkers", []))
        print(f"   + {old} noncurrent version(s) ({human(oldb)}) and {marks} delete marker(s)")
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
