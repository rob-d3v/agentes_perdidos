#!/usr/bin/env python3
"""Guardian restore — disaster recovery from the PRIVATE B2 bucket.

Pulls volume tarballs that backup_guardian.py pushed and rebuilds docker volumes on a
fresh machine. Reads the same /etc/guardian/config.json for B2 creds (or pass --config).

Typical DR flow on a NEW VPS:
  1. install docker + the PaaS (Coolify / Dokploy) but DON'T let it create apps yet
  2. guardian-restore list                          # see what hosts/dates exist in B2
  3. guardian-restore restore --host coolify --all  # recreate every volume from latest
  4. (re)install / start the PaaS pointing at the restored control-plane volume
  5. redeploy apps — their data volumes are already populated

  guardian-restore list [--host H]
  guardian-restore show --host H [--when latest|daily:YYYYMMDD|weekly:YYYYMMDD]
  guardian-restore restore --host H (--all | --volume NAME ...) [--when ...] [--force] [--dry-run]
  guardian-restore get --host H --volume NAME --dest file.tar.gz [--when ...]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile

DEFAULT_CONFIG = os.environ.get("GUARDIAN_CONFIG", "/etc/guardian/config.json")

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass


def load_b2(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    b2 = cfg.get("b2", {})
    if not b2.get("endpoint") and b2.get("region"):
        b2["endpoint"] = f"https://s3.{b2['region']}.backblazeb2.com"
    return b2


def client(b2: dict):
    import boto3
    return boto3.client("s3", endpoint_url=b2["endpoint"], aws_access_key_id=b2["key_id"],
                        aws_secret_access_key=b2["application_key"],
                        region_name=b2.get("region", "us-east-005"))


def human(n: int) -> str:
    for u, d in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= d: return f"{n/d:.1f}{u}"
    return f"{n}B"


def list_hosts(s3, bucket: str) -> list[str]:
    res = s3.list_objects_v2(Bucket=bucket, Prefix="guardian/", Delimiter="/")
    return [p["Prefix"].split("/")[1] for p in res.get("CommonPrefixes", [])]


def latest_manifest(s3, bucket: str, host: str) -> dict:
    o = s3.get_object(Bucket=bucket, Key=f"guardian/{host}/LATEST.json")
    return json.loads(o["Body"].read())


def resolve_key(s3, bucket: str, host: str, volume: str, when: str) -> str:
    """when = latest | daily:YYYYMMDD | weekly:YYYYMMDD."""
    if when == "latest":
        man = latest_manifest(s3, bucket, host)
        v = man["volumes"].get(volume)
        if not v: sys.exit(f"volume {volume} not in latest manifest for {host}")
        return v.get("daily") or v["weekly"]
    kind, _, date = when.partition(":")
    if kind not in ("daily", "weekly") or not date:
        sys.exit("--when must be latest | daily:YYYYMMDD | weekly:YYYYMMDD")
    return f"guardian/{host}/{volume}/{kind}/{date}.tar.gz"


def manifest_volumes(s3, bucket: str, host: str) -> list[str]:
    return sorted(latest_manifest(s3, bucket, host)["volumes"].keys())


def cmd_list(s3, bucket, args):
    hosts = [args.host] if args.host else list_hosts(s3, bucket)
    for h in hosts:
        print(f"\n=== host: {h} ===")
        try:
            man = latest_manifest(s3, bucket, h)
            print(f"latest manifest: {man['ts']}  ({len(man['volumes'])} volumes)")
        except Exception:
            print("(no LATEST.json)")
        pag = s3.get_paginator("list_objects_v2")
        vols = {}
        for page in pag.paginate(Bucket=bucket, Prefix=f"guardian/{h}/"):
            for o in page.get("Contents", []):
                parts = o["Key"].split("/")
                if len(parts) >= 5 and parts[3] in ("daily", "weekly"):
                    vols.setdefault(parts[2], {"daily": [], "weekly": []})
                    vols[parts[2]][parts[3]].append((parts[4].replace(".tar.gz", ""), o["Size"]))
        for v in sorted(vols):
            d = ",".join(x[0] for x in sorted(vols[v]["daily"]))
            w = ",".join(x[0] for x in sorted(vols[v]["weekly"]))
            sz = human(max((x[1] for x in vols[v]["daily"] + vols[v]["weekly"]), default=0))
            print(f"  {v}  (~{sz})\n     daily : {d or '—'}\n     weekly: {w or '—'}")
    print()


def cmd_show(s3, bucket, args):
    man = latest_manifest(s3, bucket, args.host)
    print(json.dumps(man, indent=2))


def download(s3, bucket, key, dest):
    s3.download_file(bucket, key, dest)


def restore_volume(s3, bucket, key, volume, force, dry):
    exists = subprocess.run(["docker", "volume", "inspect", volume],
                            capture_output=True).returncode == 0
    if exists and not force:
        print(f"  SKIP {volume}: exists (use --force to overwrite contents)")
        return False
    if dry:
        print(f"  DRY restore {key} -> volume {volume}")
        return True
    subprocess.run(["docker", "volume", "create", volume], capture_output=True, check=False)
    with tempfile.TemporaryDirectory() as tmp:
        tar = os.path.join(tmp, "v.tar.gz")
        download(s3, bucket, key, tar)
        # wipe then extract into the volume
        cmd = ["docker", "run", "--rm", "-v", f"{volume}:/data", "-v", f"{tmp}:/backup",
               "alpine", "sh", "-c",
               "rm -rf /data/* /data/..?* /data/.[!.]* 2>/dev/null; tar xzf /backup/v.tar.gz -C /data"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  FAIL {volume}: {r.stderr.strip()[:200]}")
            return False
    print(f"  OK {volume}  <- {key}")
    return True


def cmd_restore(s3, bucket, args):
    if args.all:
        volumes = manifest_volumes(s3, bucket, args.host)
    elif args.volume:
        volumes = args.volume
    else:
        sys.exit("pass --all or --volume NAME [NAME ...]")
    print(f"Restoring {len(volumes)} volume(s) on host '{args.host}' (when={args.when}, force={args.force}):")
    done = 0
    for v in volumes:
        try:
            key = resolve_key(s3, bucket, args.host, v, args.when)
            done += restore_volume(s3, bucket, key, v, args.force, args.dry_run)
        except Exception as e:
            print(f"  ERROR {v}: {e}")
    print(f"\n{done}/{len(volumes)} restored.")
    print("Next: (re)start the PaaS so it picks up the restored control-plane volume, then redeploy apps.")


def cmd_get(s3, bucket, args):
    key = resolve_key(s3, bucket, args.host, args.volume[0], args.when)
    download(s3, bucket, key, args.dest)
    print(f"OK {key} -> {args.dest}")


def main():
    ap = argparse.ArgumentParser(description="Guardian DR restore from B2")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list"); p.add_argument("--host"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show"); p.add_argument("--host", required=True)
    p.add_argument("--when", default="latest"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("restore"); p.add_argument("--host", required=True)
    p.add_argument("--all", action="store_true"); p.add_argument("--volume", nargs="*")
    p.add_argument("--when", default="latest"); p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("get"); p.add_argument("--host", required=True)
    p.add_argument("--volume", nargs=1, required=True); p.add_argument("--dest", required=True)
    p.add_argument("--when", default="latest"); p.set_defaults(fn=cmd_get)

    args = ap.parse_args()
    b2 = load_b2(args.config)
    s3 = client(b2)
    args.fn(s3, b2["bucket"], args)


if __name__ == "__main__":
    main()
