#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=1.40",
#     "google-genai>=1.0",
#     "pillow>=10",
#     "python-dotenv>=1.0",
# ]
# ///
"""
imagegen.py — the image-creator agent's hands.

Routes an image request to the best provider and saves the result to disk:
  - TRANSPARENT background  -> OpenAI gpt-image-1.5 (native alpha PNG)
  - NORMAL / photographic   -> Google Gemini "Nano Banana" (no alpha)

Run with uv (auto-installs deps from the inline metadata above):

  uv run imagegen.py generate --prompt "a red maple leaf" --out leaf.png --transparent
  uv run imagegen.py generate --prompt "cozy cabin at sunset" --out bg.jpg --opaque --aspect 16:9
  uv run imagegen.py generate --prompt "add a hat" --ref char.png --out char2.png --opaque

The routing rules and decision matrix live in SKILL.md — read that first.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (override via .env or --model). Verified current as of 2026-06;
# model names shift fast — if a call 404s, check the provider's model list.
# ---------------------------------------------------------------------------
OPENAI_MODEL_OPAQUE = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
OPENAI_MODEL_TRANSPARENT = os.getenv("OPENAI_IMAGE_MODEL_TRANSPARENT", "gpt-image-1.5")
GEMINI_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")

# Aspect ratio -> OpenAI size (OpenAI only supports these three buckets on
# gpt-image-1.5; everything maps to nearest).
_OPENAI_SIZE = {
    "1:1": "1024x1024",
    "3:2": "1536x1024", "16:9": "1536x1024", "4:3": "1536x1024", "5:4": "1536x1024", "21:9": "1536x1024",
    "2:3": "1024x1536", "9:16": "1024x1536", "3:4": "1024x1536", "4:5": "1024x1536",
}
_TRANSPARENT_OK_EXT = {".png", ".webp"}


def _eprint(*a):
    print(*a, file=sys.stderr)


def _load_env():
    """Load .env walking up from this file to the repo root."""
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
    load_dotenv()  # fall back to CWD / process env


# ---------------------------------------------------------------------------
# OpenAI route (transparency-capable)
# ---------------------------------------------------------------------------
def gen_openai(prompt: str, out: Path, *, transparent: bool, aspect: str,
               quality: str, model: str | None, ref: Path | None) -> dict:
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("ERROR: OPENAI_API_KEY not set (see .env / .env.example).")

    ext = out.suffix.lower()
    if transparent and ext not in _TRANSPARENT_OK_EXT:
        raise SystemExit(
            f"ERROR: transparent output needs a .png or .webp extension, got '{ext}'. "
            f"JPEG has no alpha channel."
        )
    out_format = {".png": "png", ".webp": "webp", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(ext, "png")
    model = model or (OPENAI_MODEL_TRANSPARENT if transparent else OPENAI_MODEL_OPAQUE)
    size = _OPENAI_SIZE.get(aspect, "1024x1024")

    client = OpenAI()
    kwargs = dict(model=model, prompt=prompt, size=size, quality=quality,
                  output_format=out_format, n=1)
    if transparent:
        kwargs["background"] = "transparent"

    if ref:
        # Edit mode: feed source image. Transparency still controllable.
        with open(ref, "rb") as fh:
            resp = client.images.edit(image=fh, **kwargs)
    else:
        resp = client.images.generate(**kwargs)

    data = base64.b64decode(resp.data[0].b64_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {"provider": "openai", "model": model, "size": size,
            "transparent": transparent, "path": str(out)}


# ---------------------------------------------------------------------------
# Gemini "Nano Banana" route (normal / photographic, no alpha)
# ---------------------------------------------------------------------------
def gen_gemini(prompt: str, out: Path, *, transparent: bool, aspect: str,
               image_size: str, model: str | None, ref: Path | None) -> dict:
    from google import genai
    from google.genai import types
    from PIL import Image

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise SystemExit("ERROR: GEMINI_API_KEY not set (see .env / .env.example).")

    if transparent:
        _eprint("WARN: Gemini cannot produce true alpha transparency. "
                "Route transparent requests to OpenAI instead. Proceeding opaque.")

    model = model or GEMINI_MODEL
    client = genai.Client()

    img_cfg = {"aspect_ratio": aspect}
    if image_size:  # 1K/2K/4K — 2K/4K only on gemini-3 image models
        img_cfg["image_size"] = image_size
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(**img_cfg),
    )

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
            return {"provider": "gemini", "model": model, "aspect": aspect,
                    "transparent": False, "path": str(out)}

    raise SystemExit("ERROR: Gemini returned no image part (possibly blocked by safety filters).")


# ---------------------------------------------------------------------------
# Router + CLI
# ---------------------------------------------------------------------------
def route(provider: str, transparent: bool) -> str:
    if provider != "auto":
        return provider
    return "openai" if transparent else "gemini"


def main(argv=None):
    p = argparse.ArgumentParser(description="image-creator agent — smart image generation")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate (or edit, with --ref) an image")
    g.add_argument("--prompt", required=True)
    g.add_argument("--out", required=True, help="output path; extension sets the format")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--transparent", action="store_true", help="alpha PNG -> OpenAI")
    mode.add_argument("--opaque", action="store_true", help="normal image -> Gemini (default)")
    g.add_argument("--provider", choices=["auto", "openai", "gemini"], default="auto")
    g.add_argument("--aspect", default="1:1",
                   help="1:1 | 16:9 | 9:16 | 3:4 | 4:3 | 3:2 | 2:3 | 21:9 ...")
    g.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="high",
                   help="OpenAI route only")
    g.add_argument("--image-size", default="", choices=["", "1K", "2K", "4K"],
                   help="Gemini route only (2K/4K need a gemini-3 image model)")
    g.add_argument("--model", default=None, help="override the model id")
    g.add_argument("--ref", default=None, help="source image for edit mode")
    g.add_argument("--json", action="store_true", help="print a JSON result line")

    args = p.parse_args(argv)
    _load_env()

    if args.cmd == "generate":
        transparent = args.transparent  # default False == opaque
        provider = route(args.provider, transparent)
        out = Path(args.out)
        ref = Path(args.ref) if args.ref else None
        if ref and not ref.exists():
            raise SystemExit(f"ERROR: --ref file not found: {ref}")

        if provider == "openai":
            result = gen_openai(args.prompt, out, transparent=transparent, aspect=args.aspect,
                                quality=args.quality, model=args.model, ref=ref)
        else:
            result = gen_gemini(args.prompt, out, transparent=transparent, aspect=args.aspect,
                                image_size=args.image_size, model=args.model, ref=ref)

        if args.json:
            print(json.dumps(result))
        else:
            print(f"OK  {result['provider']}:{result['model']}  ->  {result['path']}")


if __name__ == "__main__":
    main()
