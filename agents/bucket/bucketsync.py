#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.34", "python-dotenv>=1.0", "requests>=2.31"]
# ///
"""
bucketsync.py — the bucket agent's hands.

Offloads a project's static, browser-served assets (images, gifs, video, fonts...)
to object storage (Cloudflare R2 and/or Backblaze B2), then rewrites the code to
point at the public bucket URLs — so the VPS stops serving heavy files and pages
load from a CDN. All operations stay working; rewrites are reversible (.bak files).

Routing by purpose ("melhor bucket de acordo com a finalidade"):
  - Hot, browser-served assets (images, gifs, fonts, small media)  -> R2  (free egress + CDN)
  - Large / video / archival / backend-only blobs                  -> B2  (cheap storage)
  (falls back to whichever provider is configured)

Pipeline:
  uv run bucketsync.py scan    <project>                 # find assets + where they're referenced
  uv run bucketsync.py upload  <project> [--provider auto|r2|b2] [--dry-run]
  uv run bucketsync.py rewrite <project> --map map.json  [--dry-run]
  uv run bucketsync.py sync    <project> [--yes]         # scan -> upload -> rewrite
  uv run bucketsync.py verify  --map map.json            # HTTP 200 check on public URLs
  uv run bucketsync.py buckets [--provider r2|b2]        # connectivity / list buckets

Read SKILL.md first for the routing rules and the safe-rewrite policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ── asset classification ────────────────────────────────────────────────────
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".avif", ".ico", ".bmp"}
VIDEO = {".mp4", ".webm", ".mov", ".m4v"}
AUDIO = {".mp3", ".ogg", ".wav", ".flac"}
FONT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
DOC = {".pdf"}
ASSET_EXT = IMAGE | VIDEO | AUDIO | FONT | DOC

SRC_EXT = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html", ".htm",
           ".css", ".scss", ".sass", ".less", ".json", ".md", ".mdx", ".astro"}
IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "target",
               ".venv", "venv", "__pycache__", ".cache", "coverage", ".turbo",
               "dist-electron", ".gradle", "vendor"}

LARGE_BYTES = 25 * 1024 * 1024  # >25MB -> archival -> B2 by default

# Capture path-like tokens ending in an asset extension, inside quotes / url()/ imports.
_EXTS_RE = "|".join(sorted((e[1:] for e in ASSET_EXT), key=len, reverse=True))
REF_RE = re.compile(
    r"""(?P<q>['"`(])(?P<path>[^'"`()\s?#]+?\.(?:%s))(?:[?#][^'"`()\s]*)?(?P=q)?""" % _EXTS_RE,
    re.IGNORECASE,
)
IMPORT_RE = re.compile(r"""\b(?:import|require)\b[^\n]*['"`][^'"`]+\.(?:%s)['"`]""" % _EXTS_RE,
                       re.IGNORECASE)


def category(ext: str) -> str:
    ext = ext.lower()
    if ext in IMAGE:
        return "gif" if ext == ".gif" else "image"
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    if ext in FONT:
        return "font"
    return "doc"


@dataclass
class Ref:
    raw: str          # exact string token found in source (what we rewrite)
    src_file: str
    line: int
    is_import: bool    # bundler import -> NOT auto-rewritten (would break the build)


@dataclass
class Asset:
    rel: str                       # path relative to project root
    abspath: str
    ext: str
    category: str
    size: int
    served: bool = False           # referenced by a URL-string in frontend code
    refs: list[Ref] = field(default_factory=list)
    provider: str = ""             # chosen bucket
    key: str = ""
    public_url: str = ""


# ── env / providers ─────────────────────────────────────────────────────────
def load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / ".env").exists():
            load_dotenv(parent / ".env")
            return
    load_dotenv()


def _s3(provider: str):
    import boto3
    from botocore.config import Config
    if provider == "r2":
        ep, ak, sk = os.getenv("R2_S3_ENDPOINT"), os.getenv("R2_ACCESS_KEY_ID"), os.getenv("R2_SECRET_ACCESS_KEY")
        region = "auto"
    elif provider == "b2":
        ep, ak, sk = os.getenv("B2_S3_ENDPOINT"), os.getenv("B2_KEY_ID"), os.getenv("B2_APPLICATION_KEY")
        region = os.getenv("B2_REGION", "us-east-005")
    else:
        raise SystemExit(f"unknown provider {provider}")
    if not (ep and ak and sk):
        raise ProviderMissing(provider)
    return boto3.client("s3", endpoint_url=ep, aws_access_key_id=ak,
                        aws_secret_access_key=sk, region_name=region,
                        config=Config(signature_version="s3v4", retries={"max_attempts": 3}))


class ProviderMissing(Exception):
    pass


def provider_configured(p: str) -> bool:
    if p == "r2":
        return all(os.getenv(k) for k in ("R2_S3_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"))
    return all(os.getenv(k) for k in ("B2_S3_ENDPOINT", "B2_KEY_ID", "B2_APPLICATION_KEY"))


def b2_authorize() -> dict:
    """Backblaze native authorize — for a bucket-scoped key it returns
    allowed.bucketName, so we can resolve the bucket without ListBuckets."""
    import requests
    kid, key = os.getenv("B2_KEY_ID"), os.getenv("B2_APPLICATION_KEY")
    r = requests.get("https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
                     auth=(kid, key), timeout=20)
    r.raise_for_status()
    return r.json()


def bucket_name(provider: str) -> str:
    env = "R2_BUCKET_NAME" if provider == "r2" else "B2_BUCKET_NAME"
    name = os.getenv(env, "").strip()
    if name:
        return name
    if provider == "b2":
        # bucket-scoped key -> authorize response carries the bucket name
        try:
            allowed = (b2_authorize().get("allowed") or {})
            if allowed.get("bucketName"):
                return allowed["bucketName"]
        except Exception:
            pass
    try:  # broad keys can list
        bs = _s3(provider).list_buckets().get("Buckets", [])
        if len(bs) == 1:
            return bs[0]["Name"]
        raise SystemExit(f"{provider}: set {env} ({len(bs)} buckets visible: "
                         f"{', '.join(b['Name'] for b in bs)})")
    except ProviderMissing:
        raise SystemExit(f"{provider} not configured (see .env)")
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(f"{provider}: can't auto-resolve bucket (key is scoped). Set {env} in .env.")


def public_base(provider: str, bucket: str) -> str:
    base = os.getenv("R2_PUBLIC_BASE_URL" if provider == "r2" else "B2_PUBLIC_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    if provider == "b2":  # native friendly URL form
        ep = os.getenv("B2_S3_ENDPOINT", "")
        m = re.search(r"s3\.([\w-]+)\.backblazeb2\.com", ep)
        host = f"https://{m.group(1).split('-')[-1] if m else 'f005'}.backblazeb2.com" if m else "https://f005.backblazeb2.com"
        # use path-style s3 endpoint as a safe default (works for public buckets)
        return f"{ep.rstrip('/')}/{bucket}"
    raise SystemExit(f"set {'R2_PUBLIC_BASE_URL' if provider=='r2' else 'B2_PUBLIC_BASE_URL'} "
                     "(public bucket domain) so rewritten URLs are correct")


# ── scan ────────────────────────────────────────────────────────────────────
def iter_files(root: Path):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in fns:
            yield Path(dp) / fn


def scan(root: Path) -> list[Asset]:
    root = root.resolve()
    assets: dict[str, Asset] = {}
    for f in iter_files(root):
        if f.suffix.lower() in ASSET_EXT:
            try:
                size = f.stat().st_size
            except OSError:
                continue
            rel = str(f.relative_to(root)).replace("\\", "/")
            assets[rel] = Asset(rel=rel, abspath=str(f), ext=f.suffix.lower(),
                                category=category(f.suffix), size=size)
    by_name: dict[str, list[Asset]] = {}
    for a in assets.values():
        by_name.setdefault(Path(a.rel).name, []).append(a)

    # find references in source
    for f in iter_files(root):
        if f.suffix.lower() not in SRC_EXT:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        import_spans = [m.span() for m in IMPORT_RE.finditer(text)]
        srel = str(f.relative_to(root)).replace("\\", "/")
        for m in REF_RE.finditer(text):
            token = m.group("path")
            name = Path(token).name
            targets = by_name.get(name)
            if not targets:
                continue
            line = text.count("\n", 0, m.start()) + 1
            is_import = any(s <= m.start() < e for s, e in import_spans)
            # pick the asset whose rel best matches the token tail
            tgt = max(targets, key=lambda a: len(os.path.commonprefix(
                [a.rel[::-1], token.lstrip("/.")[::-1]])))
            tgt.refs.append(Ref(raw=token, src_file=srel, line=line, is_import=is_import))
            if not is_import:
                tgt.served = True
    return list(assets.values())


# ── routing ─────────────────────────────────────────────────────────────────
def choose_provider(a: Asset, prefer: str) -> str:
    have_r2, have_b2 = provider_configured("r2"), provider_configured("b2")
    if prefer in ("r2", "b2"):
        return prefer
    # auto: hot small browser assets -> R2; large/video/archival -> B2
    wants_b2 = a.size >= LARGE_BYTES or a.category in ("video", "doc")
    if wants_b2 and have_b2:
        return "b2"
    if not wants_b2 and have_r2:
        return "r2"
    return "r2" if have_r2 else "b2"


def make_key(project: str, a: Asset) -> str:
    # short content hash busts CDN cache when a file changes; keeps name readable
    h = hashlib.sha1(Path(a.abspath).read_bytes()).hexdigest()[:8]
    stem = Path(a.rel).as_posix().lstrip("/")
    return f"{project}/{a.category}/{h}-{Path(stem).name}"


# ── upload ──────────────────────────────────────────────────────────────────
def upload(project: str, assets: list[Asset], prefer: str, dry: bool,
           include_orphans: bool, force: bool) -> dict[str, str]:
    mapping: dict[str, str] = {}
    clients: dict[str, object] = {}
    names: dict[str, str] = {}
    for a in assets:
        if not a.served and not include_orphans:
            continue
        a.provider = choose_provider(a, prefer)
        if a.provider not in names:
            names[a.provider] = bucket_name(a.provider)
        bkt = names[a.provider]
        a.key = make_key(project, a)
        a.public_url = f"{public_base(a.provider, bkt)}/{a.key}"
        ctype = mimetypes.guess_type(a.rel)[0] or "application/octet-stream"
        cache = "public, max-age=31536000, immutable"
        print(f"  [{a.provider}] {a.rel}  ({a.size//1024} KB, {a.category})  -> {a.key}")
        if dry:
            mapping.update({r.raw: a.public_url for r in a.refs if not r.is_import})
            continue
        cli = clients.setdefault(a.provider, _s3(a.provider))
        exists = False
        if not force:
            try:
                cli.head_object(Bucket=bkt, Key=a.key)
                exists = True
            except Exception:
                exists = False
        if not exists:
            cli.upload_file(a.abspath, bkt, a.key,
                            ExtraArgs={"ContentType": ctype, "CacheControl": cache})
        for r in a.refs:
            if not r.is_import:
                mapping[r.raw] = a.public_url
    return mapping


# ── rewrite ─────────────────────────────────────────────────────────────────
def rewrite(root: Path, mapping: dict[str, str], dry: bool, backup: bool) -> int:
    root = root.resolve()
    # longest tokens first so we don't partially replace a longer path
    pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    changed = 0
    for f in iter_files(root):
        if f.suffix.lower() not in SRC_EXT:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        new = text
        for old, url in pairs:
            if old in new:
                new = new.replace(old, url)
        if new != text:
            changed += 1
            rel = f.relative_to(root)
            print(f"  ~ {rel}")
            if not dry:
                if backup:
                    f.with_suffix(f.suffix + ".bak").write_text(text, encoding="utf-8")
                f.write_text(new, encoding="utf-8")
    return changed


# ── verify ──────────────────────────────────────────────────────────────────
def verify(mapping: dict[str, str]) -> int:
    import requests
    bad = 0
    for url in sorted(set(mapping.values())):
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            if r.status_code >= 400:
                r = requests.get(url, timeout=20, stream=True)
            ok = r.status_code < 400
        except Exception as e:
            ok, r = False, e
        print(f"  {'OK ' if ok else 'ERR'} {getattr(r,'status_code','-')}  {url}")
        bad += 0 if ok else 1
    return bad


# ── report ──────────────────────────────────────────────────────────────────
def report(assets: list[Asset]):
    served = [a for a in assets if a.served]
    orphan = [a for a in assets if not a.served]
    imports = [a for a in assets if any(r.is_import for r in a.refs)]
    tot = sum(a.size for a in served)
    print(f"\nScan: {len(assets)} assets | {len(served)} browser-served "
          f"({tot//1024} KB) | {len(orphan)} orphan | {len(imports)} via bundler-import")
    bycat: dict[str, int] = {}
    for a in served:
        bycat[a.category] = bycat.get(a.category, 0) + 1
    if bycat:
        print("  served by type: " + ", ".join(f"{k}:{v}" for k, v in sorted(bycat.items())))
    if imports:
        print("  NOTE: bundler-import assets are NOT auto-rewritten (would break the build):")
        for a in imports[:12]:
            print(f"    - {a.rel}")
    if orphan:
        print(f"  NOTE: {len(orphan)} unreferenced asset(s) — pass --include-orphans to upload anyway.")


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv=None):
    p = argparse.ArgumentParser(description="bucket agent — offload static assets to R2/B2")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "upload", "sync"):
        sp = sub.add_parser(name)
        sp.add_argument("project")
        sp.add_argument("--provider", choices=["auto", "r2", "b2"], default="auto")
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--include-orphans", action="store_true")
        sp.add_argument("--force", action="store_true", help="re-upload even if key exists")
        sp.add_argument("--map", default=None, help="path to write the mapping json")
        sp.add_argument("--no-backup", action="store_true")
        sp.add_argument("--yes", action="store_true", help="sync: skip confirmation")
    rw = sub.add_parser("rewrite")
    rw.add_argument("project")
    rw.add_argument("--map", required=True)
    rw.add_argument("--dry-run", action="store_true")
    rw.add_argument("--no-backup", action="store_true")
    vf = sub.add_parser("verify")
    vf.add_argument("--map", required=True)
    bk = sub.add_parser("buckets")
    bk.add_argument("--provider", choices=["r2", "b2"], default="b2")

    args = p.parse_args(argv)
    load_env()

    if args.cmd == "buckets":
        try:
            name = bucket_name(args.provider)
        except SystemExit as e:
            raise e
        try:
            cli = _s3(args.provider)
            cli.head_bucket(Bucket=name)
            base = public_base(args.provider, name)
            print(f"{args.provider}: connected. bucket='{name}' reachable. public base: {base}")
        except ProviderMissing:
            raise SystemExit(f"{args.provider} not configured in .env")
        except Exception as e:
            print(f"{args.provider}: bucket='{name}' resolved, but access check failed: {e}")
        return

    if args.cmd == "verify":
        mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
        sys.exit(1 if verify(mapping) else 0)

    if args.cmd == "rewrite":
        mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
        n = rewrite(Path(args.project), mapping, args.dry_run, not args.no_backup)
        print(f"\n{'[dry-run] would change' if args.dry_run else 'changed'} {n} file(s)")
        return

    # scan / upload / sync
    project_path = Path(args.project)
    project = project_path.resolve().name
    assets = scan(project_path)
    report(assets)

    if args.cmd == "scan":
        if args.map:
            Path(args.map).write_text(json.dumps([asdict(a) for a in assets], indent=2), encoding="utf-8")
            print(f"\nmanifest -> {args.map}")
        return

    if args.cmd == "sync" and not args.yes and not args.dry_run:
        print("\nThis uploads served assets and REWRITES source files. Re-run with --yes (or --dry-run first).")
        return

    print(f"\nUploading (provider={args.provider}{' DRY-RUN' if args.dry_run else ''}):")
    mapping = upload(project, assets, args.provider, args.dry_run, args.include_orphans, args.force)
    map_path = args.map or f"bucket-map-{project}.json"
    Path(map_path).write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"\nmapping ({len(mapping)} refs) -> {map_path}")

    if args.cmd == "sync":
        print("\nRewriting source:")
        n = rewrite(project_path, mapping, args.dry_run, not args.no_backup)
        print(f"{'[dry-run] would change' if args.dry_run else 'changed'} {n} file(s)")
        if not args.dry_run:
            print("Verifying public URLs:")
            verify(mapping)


if __name__ == "__main__":
    main()
