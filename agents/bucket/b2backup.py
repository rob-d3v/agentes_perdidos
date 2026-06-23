#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3"]
# ///
"""b2backup — offsite backup of a directory to a PRIVATE Backblaze B2 bucket.

Companion to the `bucket` agent, but for ARCHIVAL/private backups (not browser-served
assets). Reads B2_PRIVATE_* from the agentes_perdidos `.env` (walked up from this script).
Tars+gzips a source dir and uploads it as a single object. Idempotent by content: the key
embeds a short content hash, so an unchanged dir is skipped.

Use it to back up llm-wiki / second-brain brains that can't (or shouldn't) be pushed to a
public git remote.

  uv run agents/bucket/b2backup.py up <src-dir> --prefix brains/<name>   # tar+upload
  uv run agents/bucket/b2backup.py up <src-dir> --prefix brains/<name> --dry-run
  uv run agents/bucket/b2backup.py ls [--prefix brains/]                 # list objects
  uv run agents/bucket/b2backup.py check                                 # connectivity

The bucket is PRIVATE by design — objects are not browser-served. Restore with any S3 client
or `b2backup.py get <key> <dest.tar.gz>`.
"""
from __future__ import annotations
import argparse, hashlib, io, os, sys, tarfile
from pathlib import Path

# force UTF-8 I/O (Windows cp1252 consoles choke on Unicode paths/titles)
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass


def load_env() -> dict:
    """Walk up from this script to find .env; parse KEY=VALUE lines."""
    env = dict(os.environ)
    here = Path(__file__).resolve()
    for d in [here.parent, *here.parents]:
        f = d / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.split("#", 1)[0].strip())
            break
    return env


def client(env: dict):
    import boto3
    ep = env.get("B2_PRIVATE_S3_ENDPOINT")
    kid = env.get("B2_PRIVATE_KEY_ID")
    ak = env.get("B2_PRIVATE_APPLICATION_KEY")
    region = env.get("B2_PRIVATE_REGION", "us-east-005")
    if not (ep and kid and ak):
        sys.exit("Missing B2_PRIVATE_S3_ENDPOINT / B2_PRIVATE_KEY_ID / B2_PRIVATE_APPLICATION_KEY in .env")
    return boto3.client("s3", endpoint_url=ep, aws_access_key_id=kid,
                        aws_secret_access_key=ak, region_name=region)


def bucket(env: dict) -> str:
    b = env.get("B2_PRIVATE_BUCKET_NAME")
    if not b:
        sys.exit("Missing B2_PRIVATE_BUCKET_NAME in .env")
    return b


def make_tar(src: Path) -> tuple[bytes, str]:
    """tar.gz a directory into memory; return (bytes, short_sha)."""
    buf = io.BytesIO()
    # deterministic-ish: sort names, drop mtime noise by using a fixed mtime
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                ti = tar.gettarinfo(str(p), arcname=str(p.relative_to(src)))
                ti.mtime = 0
                with open(p, "rb") as fh:
                    tar.addfile(ti, fh)
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()[:12]
    return data, sha


def cmd_up(args, env):
    src = Path(args.src).resolve()
    if not src.is_dir():
        sys.exit(f"not a directory: {src}")
    data, sha = make_tar(src)
    prefix = (args.prefix or src.name).strip("/")
    key = f"{prefix}/{sha}.tar.gz"
    mb = len(data) / 1e6
    s3 = client(env); bkt = bucket(env)
    # skip if exact content already there
    try:
        s3.head_object(Bucket=bkt, Key=key)
        print(f"SKIP (exists) {key}  ({mb:.2f} MB)")
        return
    except Exception:
        pass
    print(f"{'DRY ' if args.dry_run else ''}UP   {src}  ->  s3://{bkt}/{key}  ({mb:.2f} MB)")
    if args.dry_run:
        return
    # S3 object metadata must be ASCII — paths may contain non-ASCII (e.g. "Repositórios").
    src_ascii = str(src).encode("ascii", "backslashreplace").decode("ascii")
    s3.put_object(Bucket=bkt, Key=key, Body=data,
                  ContentType="application/gzip",
                  Metadata={"src": src_ascii, "sha256_12": sha})
    # also write/refresh a 'latest' pointer for easy restore
    s3.put_object(Bucket=bkt, Key=f"{prefix}/LATEST.txt", Body=key.encode(),
                  ContentType="text/plain")
    print(f"OK   uploaded + LATEST -> {key}")


def cmd_ls(args, env):
    s3 = client(env); bkt = bucket(env)
    kw = {"Bucket": bkt}
    if args.prefix:
        kw["Prefix"] = args.prefix
    total = 0; n = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(**kw):
        for o in page.get("Contents", []):
            n += 1; total += o["Size"]
            print(f"{o['Size']:>12}  {o['Key']}")
    print(f"-- {n} objects, {total/1e6:.2f} MB total")


def cmd_get(args, env):
    s3 = client(env); bkt = bucket(env)
    s3.download_file(bkt, args.key, args.dest)
    print(f"OK  {args.key} -> {args.dest}")


def cmd_check(args, env):
    s3 = client(env); bkt = bucket(env)
    s3.head_bucket(Bucket=bkt)
    print(f"OK  bucket reachable: {bkt} @ {env.get('B2_PRIVATE_S3_ENDPOINT')}")


def main():
    ap = argparse.ArgumentParser(description="Private B2 backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("up"); p.add_argument("src"); p.add_argument("--prefix", default=None)
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_up)
    p = sub.add_parser("ls"); p.add_argument("--prefix", default=None); p.set_defaults(fn=cmd_ls)
    p = sub.add_parser("get"); p.add_argument("key"); p.add_argument("dest"); p.set_defaults(fn=cmd_get)
    p = sub.add_parser("check"); p.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    env = load_env()
    args.fn(args, env)


if __name__ == "__main__":
    main()
