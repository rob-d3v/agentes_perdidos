#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=1.40",
#     "google-genai>=1.0",
#     "pillow>=10",
#     "python-dotenv>=1.0",
#     "requests>=2.31",
#     "pyjwt>=2.8",
# ]
# ///
"""
imagegen.py — the image-creator agent's hands.

Three providers, routed to their strengths, with automatic fallback:
  - TRANSPARENT image  -> OpenAI gpt-image-1.5      (only one with native alpha)
  - NORMAL image       -> Gemini "Nano Banana"      (cheap, photoreal) -> OpenAI -> Kling
  - VIDEO              -> Kling AI                   (text2video / image2video)

Every generation is costed and logged to a local usage ledger.

Run with uv (auto-installs deps from the inline metadata above):

  uv run imagegen.py generate --prompt "a red maple leaf" --out leaf.png --transparent
  uv run imagegen.py generate --prompt "cozy cabin at sunset" --out bg.jpg --opaque --aspect 16:9
  uv run imagegen.py video    --prompt "camera pushes in slowly" --ref char.png --out clip.mp4
  uv run imagegen.py usage                      # spending: today / last 7 days / all-time

Routing rules + decision matrix live in SKILL.md — read that first.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (override via .env or --model). Verified current as of 2026-06;
# model names shift fast — if a call 404s, check the provider's model list.
# ---------------------------------------------------------------------------
OPENAI_MODEL_OPAQUE = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
OPENAI_MODEL_TRANSPARENT = os.getenv("OPENAI_IMAGE_MODEL_TRANSPARENT", "gpt-image-1.5")
GEMINI_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
KLING_IMAGE_MODEL = os.getenv("KLING_IMAGE_MODEL", "kling-v2")
KLING_VIDEO_MODEL = os.getenv("KLING_VIDEO_MODEL", "kling-v2-1")
KLING_API_BASE = os.getenv("KLING_API_BASE", "https://api.klingai.com").rstrip("/")

# Preference order per task. Capability gates filter this further.
CHAIN_OPAQUE = ["gemini", "openai", "kling"]
CHAIN_TRANSPARENT = ["openai"]  # only OpenAI does true alpha

_OPENAI_SIZE = {
    "1:1": "1024x1024",
    "3:2": "1536x1024", "16:9": "1536x1024", "4:3": "1536x1024", "5:4": "1536x1024", "21:9": "1536x1024",
    "2:3": "1024x1536", "9:16": "1024x1536", "3:4": "1024x1536", "4:5": "1024x1536",
}
_TRANSPARENT_OK_EXT = {".png", ".webp"}

LEDGER = Path(__file__).resolve().parent / ".usage" / "ledger.jsonl"


class ProviderUnavailable(Exception):
    """Provider can't be used (e.g. no API key) — try the next in the chain."""


def _eprint(*a):
    print(*a, file=sys.stderr)


def _load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env = parent / ".env"
        if env.exists():
            load_dotenv(env)
            return
    load_dotenv()


# ---------------------------------------------------------------------------
# Cost estimation (USD, approximate — providers price by tokens/seconds/credits).
# ---------------------------------------------------------------------------
def estimate_cost(provider: str, model: str, *, kind: str = "image", size: str | None = None,
                  quality: str = "high", duration: float | None = None, kmode: str = "pro") -> float:
    if provider == "gemini":
        return 0.039  # ~1K image
    if provider == "openai":
        base = {"1024x1024": 0.13, "1536x1024": 0.19, "1024x1536": 0.19}.get(size or "", 0.13)
        q = {"low": 0.25, "medium": 0.5, "high": 1.0, "auto": 1.0}.get(quality, 1.0)
        if model and model.startswith("gpt-image-2"):
            base *= 1.6  # gpt-image-2 is pricier than 1.5
        return round(base * q, 4)
    if provider == "kling":
        if kind == "video":
            rate = 0.14 if kmode == "pro" else 0.07  # per second
            return round(rate * float(duration or 5), 4)
        return 0.01  # kolors image, sub-cent–cent
    return 0.0


def _find_repo_root(p: Path) -> Path | None:
    """Walk up from p looking for a .git dir (the project's main repo root)."""
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return None


def backup_output(out_path) -> Path | None:
    """Copy a freshly written asset to a backup folder OUTSIDE its main repo.

    Layout (default): <repo_parent>/_asset-backups/<repo_name>/<path-rel-to-repo>
    Override the backups root with env IMAGEGEN_BACKUP_ROOT.
    Disable entirely with IMAGEGEN_BACKUP=0.
    """
    if os.getenv("IMAGEGEN_BACKUP", "1") in ("0", "false", "no", ""):
        return None
    out = Path(out_path).resolve()
    if not out.exists():
        return None
    repo = _find_repo_root(out)
    env_root = os.getenv("IMAGEGEN_BACKUP_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        dest = root / (repo.name / out.relative_to(repo) if repo else Path(out.name))
    elif repo:
        # sibling of the repo so backups live OUTSIDE the tracked project
        dest = repo.parent / "_asset-backups" / repo.name / out.relative_to(repo)
    else:
        dest = out.parent / "_asset-backups" / out.name
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, dest)
        return dest
    except Exception as e:  # backup must never break a generation
        _eprint(f"  WARN: backup failed: {type(e).__name__}: {e}")
        return None


def log_usage(rec: dict):
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _read_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _spend_summary():
    rows = _read_ledger()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    today = now.date()
    totals = {"all": 0.0, "week": 0.0, "today": 0.0}
    by_provider: dict[str, float] = {}
    for r in rows:
        c = float(r.get("cost_usd", 0) or 0)
        ts = datetime.fromisoformat(r["ts"]) if r.get("ts") else now
        totals["all"] += c
        by_provider[r.get("provider", "?")] = by_provider.get(r.get("provider", "?"), 0.0) + c
        if ts >= week_ago:
            totals["week"] += c
        if ts.date() == today:
            totals["today"] += c
    return totals, by_provider, len(rows)


def print_running(provider: str, cost: float):
    totals, _, _ = _spend_summary()
    _eprint(f"  ~${cost:.3f} (est) via {provider}  |  today ~${totals['today']:.2f}  "
            f"|  7d ~${totals['week']:.2f}  |  all-time ~${totals['all']:.2f}")


# ---------------------------------------------------------------------------
# OpenAI route (transparency-capable)
# ---------------------------------------------------------------------------
def gen_openai(prompt, out: Path, *, transparent, aspect, quality, model, ref) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise ProviderUnavailable("OPENAI_API_KEY not set")
    from openai import OpenAI

    ext = out.suffix.lower()
    if transparent and ext not in _TRANSPARENT_OK_EXT:
        raise SystemExit(f"ERROR: transparent output needs .png/.webp, got '{ext}' (JPEG has no alpha).")
    out_format = {".png": "png", ".webp": "webp", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(ext, "png")
    model = model or (OPENAI_MODEL_TRANSPARENT if transparent else OPENAI_MODEL_OPAQUE)
    size = _OPENAI_SIZE.get(aspect, "1024x1024")

    client = OpenAI()
    kwargs = dict(model=model, prompt=prompt, size=size, quality=quality, output_format=out_format, n=1)
    if transparent:
        kwargs["background"] = "transparent"
    if ref:
        with open(ref, "rb") as fh:
            resp = client.images.edit(image=fh, **kwargs)
    else:
        resp = client.images.generate(**kwargs)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(resp.data[0].b64_json))
    cost = estimate_cost("openai", model, size=size, quality=quality)
    return {"provider": "openai", "model": model, "kind": "image", "detail": size,
            "transparent": transparent, "cost_usd": cost, "path": str(out)}


# ---------------------------------------------------------------------------
# Gemini "Nano Banana" route (normal / photographic, no alpha)
# ---------------------------------------------------------------------------
def gen_gemini(prompt, out: Path, *, transparent, aspect, image_size, model, ref) -> dict:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise ProviderUnavailable("GEMINI_API_KEY not set")
    from google import genai
    from google.genai import types
    from PIL import Image

    if transparent:
        raise ProviderUnavailable("Gemini cannot produce alpha transparency")

    model = model or GEMINI_MODEL
    client = genai.Client()
    img_cfg = {"aspect_ratio": aspect}
    if image_size:
        img_cfg["image_size"] = image_size
    config = types.GenerateContentConfig(response_modalities=["IMAGE"],
                                         image_config=types.ImageConfig(**img_cfg))
    contents: list = [prompt]
    if ref:
        contents.append(Image.open(ref))
    resp = client.models.generate_content(model=model, contents=contents, config=config)

    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            img = Image.open(BytesIO(part.inline_data.data))
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() in {".jpg", ".jpeg"} and img.mode in {"RGBA", "P"}:
                img = img.convert("RGB")
            img.save(out)
            cost = estimate_cost("gemini", model)
            return {"provider": "gemini", "model": model, "kind": "image", "detail": aspect,
                    "transparent": False, "cost_usd": cost, "path": str(out)}
    raise RuntimeError("Gemini returned no image part (possibly safety-blocked)")


# ---------------------------------------------------------------------------
# Kling AI — JWT auth, async submit/poll. Image (opaque) + video.
# ---------------------------------------------------------------------------
def _kling_token() -> str:
    import jwt
    ak, sk = os.getenv("KLING_ACCESS_KEY"), os.getenv("KLING_SECRET_KEY")
    if not (ak and sk):
        raise ProviderUnavailable("KLING_ACCESS_KEY / KLING_SECRET_KEY not set")
    now = int(time.time())
    return jwt.encode({"iss": ak, "exp": now + 1800, "nbf": now - 5}, sk,
                      algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})


def _kling_headers() -> dict:
    return {"Authorization": f"Bearer {_kling_token()}", "Content-Type": "application/json"}


def _kling_submit_poll(submit_path: str, body: dict, result_key: str, *, timeout_s=600) -> str:
    """POST to submit_path, poll until done, return first result URL (images|videos)."""
    import requests
    r = requests.post(f"{KLING_API_BASE}{submit_path}", headers=_kling_headers(), json=body, timeout=60)
    r.raise_for_status()
    task_id = r.json()["data"]["task_id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(5)
        q = requests.get(f"{KLING_API_BASE}{submit_path}/{task_id}", headers=_kling_headers(), timeout=60)
        q.raise_for_status()
        data = q.json()["data"]
        status = data["task_status"]
        if status == "succeed":
            return data["task_result"][result_key][0]["url"]
        if status == "failed":
            raise RuntimeError(f"Kling task failed: {data.get('task_status_msg', '')}")
    raise RuntimeError("Kling task timed out")


def _img_to_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def gen_kling_image(prompt, out: Path, *, transparent, aspect, model, ref) -> dict:
    if transparent:
        raise ProviderUnavailable("Kling cannot produce alpha transparency")
    import requests
    from PIL import Image
    model = model or KLING_IMAGE_MODEL
    body = {"model_name": model, "prompt": prompt, "aspect_ratio": aspect, "n": 1}
    if ref:
        body["image"] = _img_to_b64(ref)
    url = _kling_submit_poll("/v1/images/generations", body, "images")
    raw = requests.get(url, timeout=120).content
    img = Image.open(BytesIO(raw))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in {".jpg", ".jpeg"} and img.mode in {"RGBA", "P"}:
        img = img.convert("RGB")
    img.save(out)
    return {"provider": "kling", "model": model, "kind": "image", "detail": aspect,
            "transparent": False, "cost_usd": estimate_cost("kling", model), "path": str(out)}


def gen_kling_video(prompt, out: Path, *, ref, aspect, duration, kmode, model) -> dict:
    import requests
    model = model or KLING_VIDEO_MODEL
    duration = str(int(duration))  # Kling wants "5"/"10"
    if ref:
        path, key = "/v1/videos/image2video", "videos"
        body = {"model_name": model, "image": _img_to_b64(ref), "prompt": prompt,
                "mode": kmode, "duration": duration}
    else:
        path, key = "/v1/videos/text2video", "videos"
        body = {"model_name": model, "prompt": prompt, "mode": kmode,
                "aspect_ratio": aspect, "duration": duration}
    url = _kling_submit_poll(path, body, key, timeout_s=900)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(requests.get(url, timeout=300).content)
    cost = estimate_cost("kling", model, kind="video", duration=float(duration), kmode=kmode)
    return {"provider": "kling", "model": model, "kind": "video",
            "detail": f"{duration}s/{kmode}", "transparent": False, "cost_usd": cost, "path": str(out)}


# ---------------------------------------------------------------------------
# Router with fallback
# ---------------------------------------------------------------------------
def build_chain(provider: str, transparent: bool) -> list[str]:
    if provider != "auto":
        return [provider]
    return CHAIN_TRANSPARENT[:] if transparent else CHAIN_OPAQUE[:]


def run_image(args) -> dict:
    transparent = args.transparent
    out = Path(args.out)
    ref = Path(args.ref) if args.ref else None
    if ref and not ref.exists():
        raise SystemExit(f"ERROR: --ref not found: {ref}")
    chain = build_chain(args.provider, transparent)
    dispatch = {
        "openai": lambda: gen_openai(args.prompt, out, transparent=transparent, aspect=args.aspect,
                                     quality=args.quality, model=args.model, ref=ref),
        "gemini": lambda: gen_gemini(args.prompt, out, transparent=transparent, aspect=args.aspect,
                                     image_size=args.image_size, model=args.model, ref=ref),
        "kling": lambda: gen_kling_image(args.prompt, out, transparent=transparent, aspect=args.aspect,
                                         model=args.model, ref=ref),
    }
    errors = []
    for i, prov in enumerate(chain):
        try:
            result = dispatch[prov]()
            if i > 0:
                _eprint(f"WARN: fell back to '{prov}' (earlier providers unavailable: "
                        f"{'; '.join(errors)})")
            return result
        except ProviderUnavailable as e:
            errors.append(f"{prov}: {e}")
        except SystemExit:
            raise
        except Exception as e:
            errors.append(f"{prov}: {type(e).__name__}: {e}")
    hint = ("\n(Transparency is OpenAI-only — set OPENAI_API_KEY.)" if transparent else "")
    raise SystemExit("ERROR: all providers failed:\n  " + "\n  ".join(errors) + hint)


def run_video(args) -> dict:
    out = Path(args.out)
    ref = Path(args.ref) if args.ref else None
    if ref and not ref.exists():
        raise SystemExit(f"ERROR: --ref not found: {ref}")
    try:
        return gen_kling_video(args.prompt, out, ref=ref, aspect=args.aspect,
                               duration=args.duration, kmode=args.kmode, model=args.model)
    except ProviderUnavailable as e:
        raise SystemExit(f"ERROR: video needs Kling — {e}")


_REC_KEYS = ("provider", "model", "kind", "detail", "transparent", "cost_usd", "path")


def _postprocess(result: dict) -> Path | None:
    """Log cost, print running spend, and back up the asset. Returns backup path."""
    log_usage({k: result[k] for k in _REC_KEYS})
    print_running(result["provider"], result["cost_usd"])
    bkp = backup_output(result["path"])
    if bkp:
        result["backup"] = str(bkp)
    return bkp


def cmd_batch(args):
    """Generate many assets from a JSON manifest — deterministic, low-token.

    Manifest: a JSON list, or {"assets": [...]} . Each item:
      {"out": "assets/x.png", "prompt": "...", "transparent": true,
       "aspect": "1:1", "provider": "auto", "ref": "ref.png",
       "model": null, "quality": "high", "image_size": "", "label": "x"}
    Only `out` and `prompt` are required. Relative `out` paths are joined to --base-dir.
    Generation continues past failures; a summary table prints at the end.
    """
    raw = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    items = raw["assets"] if isinstance(raw, dict) else raw
    base = Path(args.base_dir).resolve() if args.base_dir else None
    results = []
    for it in items:
        out = it["out"]
        if base and not Path(out).is_absolute():
            out = str(base / out)
        label = it.get("label") or Path(out).name
        transparent = bool(it.get("transparent", False))
        ns = argparse.Namespace(
            cmd="generate", prompt=it["prompt"], out=out,
            transparent=transparent, opaque=not transparent,
            provider=it.get("provider", "auto"), aspect=it.get("aspect", "1:1"),
            quality=it.get("quality", "high"), image_size=it.get("image_size", ""),
            model=it.get("model"), ref=it.get("ref"), json=False,
        )
        print(f"### {label}")
        try:
            result = run_image(ns)
            bkp = _postprocess(result)
            print(f"OK  {result['provider']}:{result['model']}  ->  {result['path']}")
            if bkp:
                print(f"    backup -> {bkp}")
            results.append((label, "ok", result["provider"], result["path"]))
        except BaseException as e:  # never let one asset abort the batch
            _eprint(f"FAIL  {label}: {type(e).__name__}: {e}")
            results.append((label, "FAILED", "-", str(e).replace(chr(10), " ")[:120]))
    ok = sum(1 for r in results if r[1] == "ok")
    print(f"\n===== BATCH SUMMARY ({ok}/{len(results)} ok) =====")
    for label, status, prov, path in results:
        print(f"  [{status:6s}] {label:26s} {prov:8s} {path}")
    print()
    cmd_usage(None)
    return 0 if ok == len(results) else 1


def cmd_usage(_args):
    totals, by_provider, n = _spend_summary()
    print(f"Image-creator spending (estimates) - {n} generations logged")
    print(f"  today     ~${totals['today']:.2f}")
    print(f"  last 7d   ~${totals['week']:.2f}")
    print(f"  all-time  ~${totals['all']:.2f}")
    if by_provider:
        print("  by provider (all-time):")
        for p, c in sorted(by_provider.items(), key=lambda kv: -kv[1]):
            print(f"    {p:8s} ~${c:.2f}")
    if not LEDGER.exists():
        print(f"  (no ledger yet at {LEDGER})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="image-creator agent — smart image/video generation")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate (or edit, with --ref) an image")
    g.add_argument("--prompt", required=True)
    g.add_argument("--out", required=True, help="output path; extension sets the format")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--transparent", action="store_true", help="alpha PNG -> OpenAI")
    mode.add_argument("--opaque", action="store_true", help="normal image (default)")
    g.add_argument("--provider", choices=["auto", "openai", "gemini", "kling"], default="auto",
                   help="auto = capability-based chain with fallback; or force one")
    g.add_argument("--aspect", default="1:1")
    g.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="high",
                   help="OpenAI route only")
    g.add_argument("--image-size", default="", choices=["", "1K", "2K", "4K"],
                   help="Gemini route only (2K/4K need a gemini-3 image model)")
    g.add_argument("--model", default=None)
    g.add_argument("--ref", default=None, help="source image for edit mode")
    g.add_argument("--json", action="store_true")

    v = sub.add_parser("video", help="generate a video via Kling (text2video or image2video)")
    v.add_argument("--prompt", required=True)
    v.add_argument("--out", required=True, help="output .mp4 path")
    v.add_argument("--ref", default=None, help="source image -> image2video (omit for text2video)")
    v.add_argument("--aspect", default="16:9")
    v.add_argument("--duration", type=int, default=5, choices=[5, 10])
    v.add_argument("--kmode", choices=["std", "pro"], default="pro")
    v.add_argument("--model", default=None)
    v.add_argument("--json", action="store_true")

    bt = sub.add_parser("batch", help="generate many assets from a JSON manifest (deterministic, low-token)")
    bt.add_argument("--manifest", required=True, help="JSON list (or {assets:[...]}) of asset specs")
    bt.add_argument("--base-dir", default=None, help="prefix joined to relative 'out' paths")

    sub.add_parser("usage", help="show estimated spending (today / 7d / all-time)")

    args = p.parse_args(argv)
    _load_env()

    if args.cmd == "usage":
        return cmd_usage(args)

    if args.cmd == "batch":
        return cmd_batch(args)

    result = run_image(args) if args.cmd == "generate" else run_video(args)
    bkp = _postprocess(result)
    if getattr(args, "json", False):
        print(json.dumps(result))
    else:
        print(f"OK  {result['provider']}:{result['model']}  ->  {result['path']}")
        if bkp:
            print(f"    backup -> {bkp}")


if __name__ == "__main__":
    main()
