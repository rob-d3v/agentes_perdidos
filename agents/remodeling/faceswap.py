#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pillow>=10",
# ]
# ///
"""
faceswap.py — the remodeling agent's face-swap recipe, on top of image-creator.

It does NOT re-implement any provider call. It builds the *correct edit prompt* for a
identity-preserving face swap and shells out to image-creator/imagegen.py with TWO
reference images:

    --ref <original>   the image whose POSE / clothes / framing / lighting we KEEP
    --ref <face>       the real person's photo whose FACE we swap IN

Routing follows image-creator's rules automatically:
  * transparent output (alpha PNG, e.g. a cut-out portrait) -> OpenAI (only alpha-capable)
  * opaque output (a scene/photo, e.g. person at a desk)    -> Gemini "Nano Banana"

So `advogado.png` (transparent cut-out) goes to OpenAI; `marco-about.jpg` (opaque scene)
goes to Gemini — no flags needed beyond --transparent on the cut-out.

imagegen.py keeps doing the cost logging, the outside-repo backup, and the fallback chain.

Run with uv:

  # transparent cut-out portrait — keep the suit/pose, swap the face (-> OpenAI)
  uv run agents/remodeling/faceswap.py swap \
      --original frontend/dist/images/advogado.png \
      --face fotos_reais/tio4.jpg \
      --out frontend/dist/images/advogado.png --transparent --aspect 3:4

  # opaque scene — keep the office/desk/pose, swap the face (-> Gemini)
  uv run agents/remodeling/faceswap.py swap \
      --original frontend/dist/images/marco-about.jpg \
      --face fotos_reais/tio.jpg \
      --out frontend/dist/images/marco-about.jpg

  # print the prompt without generating (to tweak wording)
  uv run agents/remodeling/faceswap.py swap --original a.png --face b.jpg --out o.png --dry-run

Face-swap rules + the anti-fake policy live in SKILL.md — read that first.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# image-creator/imagegen.py sits alongside this agent's folder:
#   agents/remodeling/faceswap.py  ->  agents/image-creator/imagegen.py
IMAGEGEN = Path(__file__).resolve().parent.parent / "image-creator" / "imagegen.py"


def _eprint(*a):
    print(*a, file=sys.stderr)


def build_prompt(extra: str = "") -> str:
    """The identity-preserving face-swap instruction. First ref = pose-to-keep,
    second ref = face-to-bring-in."""
    p = (
        "Two reference images are provided. The FIRST image is the base. The SECOND image "
        "shows the real person. Edit the FIRST image so the person's FACE and HEAD become "
        "the person from the SECOND image. "
        "KEEP from the first image, unchanged: the exact pose, body position, hands, clothing "
        "and outfit, framing/crop, camera angle, background, and the lighting and color grading. "
        "BRING from the second image: the facial features, face shape, skin tone, apparent age, "
        "hairstyle and hair color, and any facial hair. "
        "The result must look like one natural, photorealistic, professional photograph of the "
        "real person — seamless blend, consistent lighting and shadows on the face, no artifacts, "
        "no collage, do not show the second image as an inset. Preserve the original's resolution "
        "and aspect ratio."
    )
    if extra:
        p += " " + extra.strip()
    return p


def build_regen_prompt(scene: str, extra: str = "") -> str:
    """Regenerate a fresh portrait FROM the real person's photo. Use this when a plain
    face-swap fails — generative editors (e.g. Gemini "Nano Banana") tend to keep the face
    already embedded in a base image and ignore a second reference. Feeding ONLY the person's
    photo + a full scene description forces the model to use their identity."""
    p = (
        "Use the exact person in the provided reference photo — keep their real face, hair "
        "(color and style), apparent age, skin tone and expression UNCHANGED. Do not make them "
        "younger and do not change their hair. Place this same person into a new photorealistic, "
        "professional photograph described as follows: " + scene.strip()
    )
    if extra:
        p += " " + extra.strip()
    return p


def cmd_regen(args) -> int:
    """Single-reference regeneration (the reliable path when swap() won't take). Opaque only;
    for a transparent cut-out, generate opaque here then run `cutout`."""
    face = Path(args.face)
    out = Path(args.out)
    if not face.exists():
        _eprint(f"ERROR: --face not found: {face}")
        return 2
    if not IMAGEGEN.exists():
        _eprint(f"ERROR: imagegen.py not found at {IMAGEGEN}")
        return 2
    prompt = build_regen_prompt(args.scene, args.extra)
    cmd = ["uv", "run", str(IMAGEGEN), "generate", "--prompt", prompt, "--out", str(out),
           "--ref", str(face), "--opaque", "--aspect", args.aspect, "--provider", args.provider]
    if args.model:
        cmd += ["--model", args.model]
    if args.dry_run:
        print("PROMPT:\n" + prompt + "\n\nWOULD RUN:\n  " + " ".join(cmd))
        return 0
    print(f"Regen: build a new scene around the person in {face.name} -> {out}")
    proc = subprocess.run(cmd)
    if proc.returncode == 0:
        print(f"OK -> {out}\nNEXT: compare with the real photos; for a transparent cut-out run `cutout`.")
    return proc.returncode


def cmd_cutout(args) -> int:
    """Remove the background of an opaque image -> transparent PNG (rembg). Use this to make a
    cut-out when OpenAI (the only alpha-capable generator) is unavailable."""
    src = Path(args.src)
    out = Path(args.out)
    if not src.exists():
        _eprint(f"ERROR: --src not found: {src}")
        return 2
    code = (
        "from rembg import remove; from PIL import Image; "
        f"Image.open(r'{src}'); "
        f"out=remove(Image.open(r'{src}')); out.save(r'{out}'); print('SAVED', out.mode, out.size)"
    )
    cmd = ["uv", "run", "--with", "rembg", "--with", "onnxruntime", "--with", "pillow",
           "python", "-c", code]
    if args.dry_run:
        print("WOULD RUN:\n  " + " ".join(cmd))
        return 0
    print(f"Cutout: remove background {src.name} -> {out} (rembg)")
    return subprocess.run(cmd).returncode


def cmd_swap(args) -> int:
    original = Path(args.original)
    face = Path(args.face)
    out = Path(args.out)
    for label, pth in (("--original", original), ("--face", face)):
        if not pth.exists():
            _eprint(f"ERROR: {label} not found: {pth}")
            return 2
    if not IMAGEGEN.exists():
        _eprint(f"ERROR: imagegen.py not found at {IMAGEGEN}")
        return 2

    prompt = build_prompt(args.extra)
    cmd = [
        "uv", "run", str(IMAGEGEN), "generate",
        "--prompt", prompt,
        "--out", str(out),
        "--ref", str(original),   # order matters: first = pose to keep
        "--ref", str(face),       #               second = real face to bring in
        "--aspect", args.aspect,
        "--provider", args.provider,
    ]
    cmd.append("--transparent" if args.transparent else "--opaque")
    if args.model:
        cmd += ["--model", args.model]
    if args.quality:
        cmd += ["--quality", args.quality]

    if args.dry_run:
        print("PROMPT:\n" + prompt + "\n")
        print("WOULD RUN:\n  " + " ".join(repr(c) if " " in c else c for c in cmd))
        return 0

    print(f"Face-swap: keep pose of {original.name}, swap in face from {face.name} -> {out}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        _eprint(f"faceswap: imagegen exited {proc.returncode}")
        return proc.returncode
    print(f"OK -> {out}")
    print("NEXT: open the output and compare with the real photos. If the likeness is off, "
          "re-run with a clearer/frontal --face photo or add --extra '...'.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="remodeling agent — identity-preserving face swap (wraps imagegen.py)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("swap", help="swap the face in --original with the person in --face, keeping the pose")
    s.add_argument("--original", required=True, help="image whose pose/clothes/lighting to KEEP")
    s.add_argument("--face", required=True, help="real person's photo whose FACE to bring in")
    s.add_argument("--out", required=True, help="output path; extension sets format (.png keeps alpha)")
    s.add_argument("--transparent", action="store_true",
                   help="output needs alpha (cut-out portrait) -> routes to OpenAI")
    s.add_argument("--aspect", default="3:4")
    s.add_argument("--provider", choices=["auto", "openai", "gemini", "kling"], default="auto")
    s.add_argument("--quality", default=None, choices=[None, "low", "medium", "high", "auto"])
    s.add_argument("--model", default=None)
    s.add_argument("--extra", default="", help="extra instruction appended to the swap prompt")
    s.add_argument("--dry-run", action="store_true", help="print prompt + command, don't generate")
    s.set_defaults(func=cmd_swap)

    r = sub.add_parser("regen", help="regenerate a portrait FROM the person's photo (reliable when swap fails on Gemini)")
    r.add_argument("--face", required=True, help="the real person's photo (sole identity source)")
    r.add_argument("--scene", required=True, help="full description of the pose/wardrobe/setting to build")
    r.add_argument("--out", required=True, help="output path (opaque; use `cutout` for transparency)")
    r.add_argument("--aspect", default="3:4")
    r.add_argument("--provider", choices=["auto", "openai", "gemini", "kling"], default="gemini")
    r.add_argument("--model", default=None)
    r.add_argument("--extra", default="")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_regen)

    c = sub.add_parser("cutout", help="remove background -> transparent PNG (rembg); for cut-outs without OpenAI")
    c.add_argument("--src", required=True, help="opaque source image")
    c.add_argument("--out", required=True, help="output .png (RGBA)")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_cutout)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
