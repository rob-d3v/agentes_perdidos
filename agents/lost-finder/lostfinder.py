#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Pillow>=10.0",
#   "pypdf>=4.0",
#   "python-dotenv>=1.0",
#   "google-genai>=1.0",
#   "mnemonic>=0.21",
# ]
# ///
"""
lostfinder — forensic hunter for lost files on a (Windows) machine.

Finds files even when they were renamed, moved, dumped in a backup, or sitting in the
Recycle Bin — because it matches on CONTENT, not just filename:

  * images  → color-signature match (e.g. "yellow logo on a blue background")
  * pdfs    → extracted-text keyword match (e.g. "esquadro engenharia obra civil")

Subcommands:
  scan     walk roots, collect candidate files (by extension), write an index.json
  images   score image candidates by color signature + filename, rank, optional copy
  pdfs     score pdf candidates by text keywords + filename, rank, optional copy
  hunt     scan + images + pdfs + report, in one shot
  report   render a markdown report from the saved scores

Run with uv (deps auto-install):
  uv run agents/lost-finder/lostfinder.py hunt --preset esquadro
"""
from __future__ import annotations

import argparse
import colorsys
import csv
import json
import os
import shutil
import sys
import time
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Presets: a "target" = what we are hunting for. Encodes the color signature
# (for images) and the keyword set (for pdfs/filenames) of one lost thing.
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    # The user's case: art for "Esquadro Engenharia" — a square/set-square (esquadro)
    # logo in YELLOW on a BLUE background — plus a PDF of civil-engineering jobs (obras).
    "esquadro": {
        "describe": "Esquadro Engenharia: yellow set-square logo on blue background + obras PDF",
        "colors": ["yellow", "blue"],          # both must be present; blue = background
        "filename_kw": [
            "esquadro", "logo", "arte", "marca", "banner", "post", "feed",
            "engenharia", "obra", "fachada", "azul", "amarelo",
        ],
        "pdf_kw": [
            "esquadro", "engenharia", "obra", "obras", "civil", "projeto", "planta",
            "arquitet", "orçament", "orcament", "construç", "construc", "reforma",
            "memorial", "cliente", "fachada", "estrutur", "fundaç", "fundac",
            "crea", "art ", "m²", "metro", "alvenaria", "concreto",
        ],
        # vision yes/no prompt for the optional `verify` stage (cuts color false-positives)
        "vision_prompt": (
            "You are screening images to find a lost company LOGO for 'Esquadro Engenharia', "
            "a civil-engineering firm. The logo is a SET-SQUARE / right-triangle ruler "
            "(esquadro) drawn in YELLOW on a BLUE background, likely with the company name. "
            "It is a clean graphic logo/brand art — NOT a photo, meme, avatar, screenshot, "
            "or unrelated illustration. Answer ONLY with compact JSON: "
            '{"match": true|false, "confidence": 0-100, "why": "<8 words>"}.'
        ),
    },
}

# Extensions we care about
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}

# Directories never worth walking (noise / system / huge)
SKIP_DIR_NAMES = {
    "node_modules", ".git", ".svn", "__pycache__", ".cache", "dist", "build",
    "target", ".venv", "venv", "site-packages", "AppData\\Local\\Temp",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$WINDOWS.~BT", "Recovery", ".gradle", ".m2", ".nuget",
}

# Sensible default hunting grounds on Windows (expanded against the user profile).
QUICK_SUBDIRS = ["Desktop", "Documents", "Downloads", "Pictures", "OneDrive",
                 "Videos", "Music", "Saved Pictures"]


# ---------------------------------------------------------------------------
# Color classification (HSV buckets). Robust to renames; cheap on thumbnails.
# ---------------------------------------------------------------------------

# hue ranges in [0,1], plus min saturation / value, per named color.
COLOR_BUCKETS = {
    "yellow": dict(h=(0.10, 0.19), s=0.35, v=0.40),
    "blue":   dict(h=(0.53, 0.72), s=0.30, v=0.20),
    "red":    dict(h=(0.95, 0.04), s=0.40, v=0.30),  # wraps 0
    "green":  dict(h=(0.25, 0.45), s=0.30, v=0.25),
    "orange": dict(h=(0.04, 0.10), s=0.45, v=0.45),
    "black":  dict(h=None, s=None, v=0.0, vmax=0.18),
    "white":  dict(h=None, s_max=0.12, v=0.85),
}


def classify_pixel(r: int, g: int, b: int) -> set[str]:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    out: set[str] = set()
    if v <= 0.18:
        out.add("black")
        return out
    if s <= 0.12 and v >= 0.85:
        out.add("white")
        return out
    for name, spec in COLOR_BUCKETS.items():
        if name in ("black", "white"):
            continue
        hr = spec["h"]
        if hr is None:
            continue
        lo, hi = hr
        in_h = (lo <= h <= hi) if lo <= hi else (h >= lo or h <= hi)
        if in_h and s >= spec["s"] and v >= spec["v"]:
            out.add(name)
    return out


def color_fractions(path: Path, max_side: int = 96) -> dict[str, float] | None:
    """Return fraction of *opaque* pixels falling in each color bucket."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow not installed — run via `uv run` so PEP-723 deps load.")
    try:
        im = Image.open(path)
        im.thumbnail((max_side, max_side))
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        rgba = im.convert("RGBA")
    except Exception:
        return None
    counts: dict[str, int] = {k: 0 for k in COLOR_BUCKETS}
    opaque = 0
    for r, g, b, a in rgba.getdata():
        if a < 32:            # treat near-transparent as "background", skip
            continue
        opaque += 1
        for name in classify_pixel(r, g, b):
            counts[name] += 1
    if opaque == 0:
        return None
    fracs = {k: counts[k] / opaque for k in counts}
    fracs["_alpha"] = 1.0 if has_alpha else 0.0
    fracs["_opaque_px"] = float(opaque)
    return fracs


def image_score(fracs: dict[str, float], want: list[str]) -> float:
    """
    0..100. Rewards BOTH wanted colors being present; for a logo-on-background,
    one color (blue) is large (bg) and the other (yellow) is a moderate accent.
    """
    if not fracs:
        return 0.0
    # generic two-color "both present" score
    parts = []
    for c in want:
        f = fracs.get(c, 0.0)
        # saturating curve: ~12% of a color already counts as "clearly present"
        parts.append(min(f / 0.12, 1.0))
    base = 1.0
    for p in parts:
        base *= p
    score = 100.0 * (base ** (1.0 / max(len(parts), 1)))  # geometric mean
    # small bonus when one color dominates like a background (>30%)
    if any(fracs.get(c, 0) > 0.30 for c in want):
        score = min(100.0, score + 8)
    return round(score, 1)


# ---------------------------------------------------------------------------
# Filename + PDF text scoring
# ---------------------------------------------------------------------------

def filename_score(path: Path, keywords: list[str]) -> tuple[int, list[str]]:
    name = path.name.lower()
    hits = [k for k in keywords if k.lower() in name]
    return len(hits), hits


def pdf_text_score(path: Path, keywords: list[str], max_pages: int = 25):
    """Return (keyword_hits, distinct_kw, n_pages, scanned_flag)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("pypdf not installed — run via `uv run`.")
    try:
        reader = PdfReader(str(path))
        n_pages = len(reader.pages)
        text = []
        for pg in reader.pages[:max_pages]:
            try:
                text.append(pg.extract_text() or "")
            except Exception:
                continue
        blob = "\n".join(text).lower()
    except Exception:
        return [], n_pages if "n_pages" in dir() else 0, True
    scanned = len(blob.strip()) < 40        # ~no extractable text → likely scanned
    hits = sorted({k.strip() for k in keywords if k.lower() in blob})
    return hits, n_pages, scanned


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    path: str
    size: int
    mtime: float
    ext: str
    kind: str  # "image" | "pdf"


def resolve_roots(args) -> list[Path]:
    if args.roots:
        return [Path(r) for r in args.roots]
    home = Path(os.path.expanduser("~"))
    if args.quick:
        roots = [home / s for s in QUICK_SUBDIRS if (home / s).exists()]
        roots.append(home / "OneDrive")
        return [r for r in roots if r.exists()]
    # default: whole user profile + every fixed drive root + recycle bins
    roots = [home]
    for d in args.drives or []:
        roots.append(Path(f"{d}:\\"))
    return [r for r in roots if r.exists()]


def should_skip(dirpath: str) -> bool:
    parts = set(Path(dirpath).parts)
    for s in SKIP_DIR_NAMES:
        if s in parts or s in dirpath:
            return True
    return False


def cmd_scan(args) -> list[Candidate]:
    roots = resolve_roots(args)
    print(f"[scan] roots: {', '.join(str(r) for r in roots)}", file=sys.stderr)
    want_ext = (IMAGE_EXTS | PDF_EXTS)
    cands: list[Candidate] = []
    seen = 0
    t0 = time.time()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
            if should_skip(dirpath):
                dirnames[:] = []
                continue
            # prune skip dirs cheaply
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith("$")]
            if args.include_recycle is False and "$Recycle.Bin" in dirpath:
                continue
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in want_ext:
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                seen += 1
                if args.min_kb and st.st_size < args.min_kb * 1024:
                    continue
                kind = "pdf" if ext in PDF_EXTS else "image"
                cands.append(Candidate(fp, st.st_size, st.st_mtime, ext, kind))
    dt = time.time() - t0
    print(f"[scan] {len(cands)} candidates ({sum(c.kind=='image' for c in cands)} img / "
          f"{sum(c.kind=='pdf' for c in cands)} pdf) in {dt:.1f}s", file=sys.stderr)
    if args.index:
        Path(args.index).write_text(
            json.dumps([asdict(c) for c in cands], ensure_ascii=False, indent=0))
        print(f"[scan] index → {args.index}", file=sys.stderr)
    return cands


def load_index(path: str) -> list[Candidate]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Candidate(**d) for d in data]


# ---------------------------------------------------------------------------
# Score images / pdfs
# ---------------------------------------------------------------------------

def cmd_images(args, cands=None):
    preset = PRESETS[args.preset]
    want = args.colors.split(",") if args.colors else preset["colors"]
    fkw = preset["filename_kw"]
    cands = cands or load_index(args.index)
    imgs = [c for c in cands if c.kind == "image"]
    print(f"[images] scoring {len(imgs)} images for colors={want} …", file=sys.stderr)
    rows = []
    for i, c in enumerate(imgs):
        if i % 200 == 0 and i:
            print(f"  …{i}/{len(imgs)}", file=sys.stderr)
        fracs = color_fractions(Path(c.path))
        cscore = image_score(fracs, want) if fracs else 0.0
        fcount, fhits = filename_score(Path(c.path), fkw)
        total = cscore + fcount * 6  # filename hits nudge ranking
        if total <= 0:
            continue
        rows.append({
            "score": round(total, 1), "color": cscore,
            "fname_hits": fhits,
            **({k: round(fracs.get(k, 0), 3) for k in want} if fracs else {}),
            "alpha": bool(fracs.get("_alpha")) if fracs else False,
            "mtime": time.strftime("%Y-%m-%d", time.localtime(c.mtime)),
            "size_kb": c.size // 1024, "path": c.path,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    _emit(rows, args, "images")
    if args.copy_top:
        _copy_top(rows, args.copy_top, args.out or "found/images")
    return rows


def cmd_pdfs(args, cands=None):
    preset = PRESETS[args.preset]
    pkw = preset["pdf_kw"]
    fkw = preset["filename_kw"]
    cands = cands or load_index(args.index)
    pdfs = [c for c in cands if c.kind == "pdf"]
    print(f"[pdfs] scanning text of {len(pdfs)} pdfs …", file=sys.stderr)
    rows = []
    for i, c in enumerate(pdfs):
        if i % 100 == 0 and i:
            print(f"  …{i}/{len(pdfs)}", file=sys.stderr)
        hits, n_pages, scanned = pdf_text_score(Path(c.path), pkw)
        fcount, fhits = filename_score(Path(c.path), fkw)
        total = len(hits) * 5 + fcount * 6 + (3 if scanned and fcount else 0)
        if total <= 0:
            continue
        rows.append({
            "score": total, "kw_hits": hits, "fname_hits": fhits,
            "pages": n_pages, "scanned": scanned,
            "mtime": time.strftime("%Y-%m-%d", time.localtime(c.mtime)),
            "size_kb": c.size // 1024, "path": c.path,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    _emit(rows, args, "pdfs")
    if args.copy_top:
        _copy_top(rows, args.copy_top, args.out or "found/pdfs")
    return rows


# ===========================================================================
# SECRETS MODE — recover a user's OWN lost wallet credentials on their OWN PC.
# Finds: BIP39 seed phrases (12/18/24 valid words, checksum-checked), wallet
# keywords in notes/txt, ETH private keys, and the MetaMask browser vault blob.
# SAFETY: everything stays local. Output is REDACTED by default. Never transmit.
# ===========================================================================

TEXT_EXTS = {".txt", ".md", ".rtf", ".csv", ".tsv", ".json", ".ini", ".cfg",
             ".conf", ".log", ".html", ".htm", ".xml", ".eml", ".note", ".asc",
             ".bak", ".old", ".text", ".yml", ".yaml", ".kdbx.txt"}
DOC_EXTS = {".docx", ".xlsx", ".odt", ".ods", ".pptx"}  # zip-of-xml, text extractable

# Words that hint a file holds wallet creds (pt-BR + en).
SECRET_KW = [
    "metamask", "seed phrase", "secret recovery phrase", "recovery phrase",
    "frase de recupera", "frase secreta", "mnemonic", "mnemônic", "mnemonico",
    "private key", "chave privada", "wallet", "carteira", "senha", "password",
    "passphrase", "12 palavras", "24 palavras", "keystore", "0x",
    "trust wallet", "phantom", "ledger", "bitcoin", "ethereum", "cripto",
]

# MetaMask extension id + where browsers keep its encrypted vault (Windows).
METAMASK_EXT_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"
BROWSER_PROFILE_ROOTS = [
    r"AppData\Local\Google\Chrome\User Data",
    r"AppData\Local\Microsoft\Edge\User Data",
    r"AppData\Local\BraveSoftware\Brave-Browser\User Data",
    r"AppData\Local\Vivaldi\User Data",
    r"AppData\Roaming\Opera Software\Opera Stable",
    r"AppData\Roaming\Opera Software\Opera GX Stable",
]
# regex for the vault JSON blob MetaMask writes into its LevelDB .ldb/.log files
VAULT_RE = None  # compiled lazily


def _bip39_wordset():
    from mnemonic import Mnemonic
    m = Mnemonic("english")
    return set(m.wordlist), m


def read_text_any(path: Path, max_bytes: int = 5_000_000) -> str:
    """Best-effort text extraction from plain text, office (zip/xml), and pdf."""
    ext = path.suffix.lower()
    try:
        if ext in DOC_EXTS:
            import zipfile, re as _re
            parts = []
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.endswith(".xml") and ("document" in n or "sheet" in n
                                               or "slide" in n or "content" in n):
                        parts.append(_re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
            return "\n".join(parts)
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in r.pages[:30])
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", "ignore")
    except Exception:
        return ""


def find_seed_phrases(text: str, wordset, mnem):
    """Return list of dicts for runs of consecutive BIP39 words (len 12/18/24)."""
    import re as _re
    tokens = _re.findall(r"[a-z]+", text.lower())
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] in wordset:
            j = i
            while j < n and tokens[j] in wordset:
                j += 1
            run = tokens[i:j]
            # slide EVERY standard length over the run — a valid 12-word phrase can
            # sit inside a longer run of dictionary words, so never stop at the first fit.
            for L in (12, 18, 24):
                if len(run) < L:
                    continue
                for s in range(0, len(run) - L + 1):
                    phrase = run[s:s + L]
                    try:
                        valid = mnem.check(" ".join(phrase))
                    except Exception:
                        valid = False
                    # keep checksum-valid windows (high precision) OR a run that is
                    # EXACTLY a standard length (likely an intended phrase w/ a typo).
                    if valid or len(run) == L:
                        out.append({"len": L, "valid": valid, "words": phrase})
            i = j
        else:
            i += 1
    # de-dup by phrase
    seen, uniq = set(), []
    for o in out:
        k = " ".join(o["words"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


def redact_phrase(words: list[str]) -> str:
    if len(words) <= 3:
        return " ".join(words)
    return f"{words[0]} {words[1]} … [{len(words)-3} hidden] … {words[-1]}"


def _ocr_image(path: Path) -> str:
    """LOCAL OCR only (Tesseract). A seed image must NEVER touch a cloud API."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "OCR needs pytesseract + the Tesseract binary (local, offline).\n"
            "  uv pip install pytesseract  AND  install Tesseract: "
            "https://github.com/UB-Mannheim/tesseract/wiki (Windows) — then re-run with --ocr.")
    try:
        return pytesseract.image_to_string(Image.open(path), lang="eng+por")
    except Exception as e:
        print(f"  [ocr] {path.name}: {e}", file=sys.stderr)
        return ""


def cmd_secrets(args):
    wordset, mnem = _bip39_wordset()
    import re as _re
    roots = resolve_roots(args)
    print(f"[secrets] roots: {', '.join(str(r) for r in roots)}", file=sys.stderr)
    print("[secrets] LOCAL-ONLY recovery of YOUR wallet. Output redacted unless --reveal.",
          file=sys.stderr)
    if args.ocr:
        print("[secrets] --ocr on: images OCR'd LOCALLY (Tesseract); nothing leaves the PC.",
              file=sys.stderr)
    pk_re = _re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b")
    want_ext = TEXT_EXTS | DOC_EXTS | {".pdf"} | (IMAGE_EXTS if args.ocr else set())
    seeds, kw_hits, pkeys = [], [], []
    files = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
            if should_skip(dirpath):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in want_ext:
                    continue
                fp = Path(dirpath) / fn
                try:
                    if fp.stat().st_size > 8_000_000:
                        continue
                except OSError:
                    continue
                ext = fp.suffix.lower()
                text = _ocr_image(fp) if ext in IMAGE_EXTS else read_text_any(fp)
                if not text:
                    continue
                files += 1
                low = text.lower()
                # 1) seed phrases (strongest signal)
                for s in find_seed_phrases(text, wordset, mnem):
                    seeds.append({**s, "path": str(fp)})
                # 2) keyword context
                hits = [k for k in SECRET_KW if k in low]
                if hits:
                    kw_hits.append({"path": str(fp), "kw": hits[:8]})
                # 3) private keys / keystore (lower confidence)
                for m in pk_re.findall(text):
                    if any(h in low for h in ("key", "metamask", "wallet", "0x", "eth")):
                        pkeys.append({"path": str(fp), "match": m[:6] + "…" + m[-4:]})
                        break
    seeds.sort(key=lambda s: (s["valid"], s["len"]), reverse=True)
    print(f"\n[secrets] scanned {files} text/doc/pdf files", file=sys.stderr)
    print(f"\n=== SEED PHRASES ({len(seeds)}) — checksum-VALID first ===")
    for s in seeds[: args.top]:
        shown = " ".join(s["words"]) if args.reveal else redact_phrase(s["words"])
        tag = "VALID✓" if s["valid"] else "unverified"
        print(f"  [{s['len']}w {tag}] {shown}\n          {s['path']}")
    print(f"\n=== FILES MENTIONING WALLET/SEED/PASSWORD KEYWORDS ({len(kw_hits)}) ===")
    for h in sorted(kw_hits, key=lambda x: -len(x["kw"]))[: args.top]:
        print(f"  {','.join(h['kw'])}\n          {h['path']}")
    print(f"\n=== POSSIBLE PRIVATE KEYS ({len(pkeys)}) ===")
    for p in pkeys[: args.top]:
        print(f"  {p['match']}   {p['path']}")
    if args.reveal:
        print("\n⚠️  Full secrets printed above — clear your terminal scrollback when done.",
              file=sys.stderr)
    # always run the vault locate too — it's the MetaMask-specific payoff
    cmd_vault(args, quiet=False)
    return {"seeds": seeds, "kw": kw_hits, "pkeys": pkeys}


def cmd_vault(args, quiet=False):
    """Locate (and optionally extract) the MetaMask encrypted vault from browsers."""
    global VAULT_RE
    import re as _re
    if VAULT_RE is None:
        # the vault is a JSON object with data/iv/salt (sometimes keyMetadata)
        VAULT_RE = _re.compile(
            r'\{\\?"data\\?":\\?"[^"\\]{40,}\\?",\\?"iv\\?":\\?"[^"\\]+\\?",'
            r'(?:\\?"keyMetadata\\?":.{0,200}?,)?\\?"salt\\?":\\?"[^"\\]+\\?"\}')
    home = Path(os.path.expanduser("~"))
    ext_dirs = []
    for rel in BROWSER_PROFILE_ROOTS:
        base = home / rel
        if not base.exists():
            continue
        # User Data has Default + Profile N; Opera Stable is itself the profile
        for sub in list(base.glob(f"*/Local Extension Settings/{METAMASK_EXT_ID}")) + \
                   list(base.glob(f"Local Extension Settings/{METAMASK_EXT_ID}")):
            ext_dirs.append(sub)
    print(f"\n=== METAMASK VAULT ({len(ext_dirs)} extension store(s) found) ===")
    if not ext_dirs:
        print("  No MetaMask extension storage found in the usual browser profiles.")
        print("  (If the wallet was on Firefox/mobile, the vault lives elsewhere — ask.)")
        return []
    found_vaults = []
    outdir = Path(args.out or "found/vault")
    for d in ext_dirs:
        print(f"  store: {d}")
        for f in list(d.glob("*.ldb")) + list(d.glob("*.log")):
            try:
                blob = f.read_bytes().decode("latin-1", "ignore")
            except Exception:
                continue
            for m in VAULT_RE.findall(blob):
                cleaned = m.replace('\\"', '"')
                if cleaned in found_vaults:
                    continue
                found_vaults.append(cleaned)
                if args.extract:
                    outdir.mkdir(parents=True, exist_ok=True)
                    vp = outdir / f"vault_{len(found_vaults)}.json"
                    vp.write_text(cleaned, encoding="utf-8")
                    print(f"    -> vault blob extracted: {vp}")
                else:
                    print(f"    -> vault blob found in {f.name} (use --extract to save it)")
    if found_vaults:
        print("\n  NEXT STEP (offline): open https://metamask.github.io/vault-decryptor/")
        print("  load the saved vault_N.json, enter your password. Forgot it? feed the blob")
        print("  to btcrecover/hashcat (modes 26600-26620) with password guesses. All offline.")
    else:
        print("  Extension store present but no vault blob matched (may be a fresh/empty wallet).")
    return found_vaults


# ---------------------------------------------------------------------------
# Optional vision verify (Gemini) — confirm an image really is the target.
# Color matching finds yellow+blue blobs (memes, avatars); vision reads content.
# ---------------------------------------------------------------------------

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


def vision_check(path: Path, prompt: str, model: str):
    """Ask Gemini yes/no. Returns dict {match,confidence,why} or None on error."""
    from google import genai
    from PIL import Image
    client = genai.Client()
    try:
        img = Image.open(path)
        img.thumbnail((768, 768))
        resp = client.models.generate_content(model=model, contents=[prompt, img])
        txt = (resp.text or "").strip().strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:].strip()
        start, end = txt.find("{"), txt.rfind("}")
        return json.loads(txt[start:end + 1]) if start >= 0 else None
    except Exception as e:
        print(f"  [vision] {path.name}: {e}", file=sys.stderr)
        return None


def cmd_verify(args):
    _load_env()
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise SystemExit("GEMINI_API_KEY not set in repo .env — needed for `verify`.")
    preset = PRESETS[args.preset]
    prompt = preset.get("vision_prompt")
    if not prompt:
        raise SystemExit(f"preset '{args.preset}' has no vision_prompt")
    model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
    # input: a CSV of image scores (from `images --csv`) or re-score now
    if args.csv_in:
        with open(args.csv_in, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = cmd_images(args)  # produces ranked rows
    rows = rows[: args.verify_top]
    print(f"[verify] vision-checking top {len(rows)} images with {model} …", file=sys.stderr)
    out = []
    for r in rows:
        v = vision_check(Path(r["path"]), prompt, model)
        if not v:
            continue
        r["vmatch"] = v.get("match")
        r["vconf"] = v.get("confidence")
        r["why"] = v.get("why", "")
        out.append(r)
        flag = "YES" if v.get("match") in (True, "true", "True") else "no "
        print(f"  [{flag}] conf={str(v.get('confidence')):>3}  {str(v.get('why',''))[:40]:<40}  {r['path']}")
    confirmed = [r for r in out if r.get("vmatch") in (True, "true", "True")]
    confirmed.sort(key=lambda r: int(r.get("vconf") or 0), reverse=True)
    print(f"\n=== VISION-CONFIRMED ({len(confirmed)}) ===")
    for r in confirmed:
        print(f"  conf={r['vconf']:>3}  {r['why']}\n          {r['path']}")
    if confirmed and args.copy_top:
        _copy_top(confirmed, args.copy_top, args.out or "found/confirmed")
    return confirmed


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _emit(rows, args, label):
    top = rows[: args.top]
    print(f"\n=== TOP {len(top)} {label.upper()} ===")
    for r in top:
        extra = ""
        if "color" in r:
            extra = f"color={r['color']} " + " ".join(
                f"{k}={r[k]}" for k in r if k in ("yellow", "blue", "red", "green"))
            if r.get("alpha"):
                extra += " [alpha]"
        if "kw_hits" in r:
            extra = f"pages={r['pages']} kw={r['kw_hits']}" + (" [SCANNED]" if r["scanned"] else "")
        fn = f" fname={r['fname_hits']}" if r.get("fname_hits") else ""
        print(f"  {r['score']:>6}  {r['mtime']}  {r['size_kb']:>6}KB  {extra}{fn}")
        print(f"          {r['path']}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["path"])
            w.writeheader()
            for r in rows:
                w.writerow({k: (",".join(v) if isinstance(v, list) else v) for k, v in r.items()})
        print(f"[{label}] full ranking → {args.csv}", file=sys.stderr)


def _copy_top(rows, n, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rows[:n]):
        src = Path(r["path"])
        if not src.exists():
            continue
        dst = out / f"{i:02d}_{r['score']}_{src.name}"
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            print(f"  copy failed {src}: {e}", file=sys.stderr)
    print(f"[copy] top {n} → {out.resolve()}  (open this folder to eyeball matches)",
          file=sys.stderr)


def cmd_hunt(args):
    cands = cmd_scan(args)
    args.copy_top = args.copy_top or 15
    imgs = cmd_images(args, cands)
    pdfs = cmd_pdfs(args, cands)
    # markdown report
    rep = Path(args.report or "found/report.md")
    rep.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# lostfinder report — preset `{args.preset}`",
             f"\n_{PRESETS[args.preset]['describe']}_\n",
             f"\nScanned, scored **{len(imgs)} image** and **{len(pdfs)} pdf** candidates.\n",
             "\n## Top image matches (yellow logo on blue bg)\n",
             "| score | date | size | colors | filename hits | path |",
             "|--:|--|--:|--|--|--|"]
    for r in imgs[: args.top]:
        cols = " ".join(f"{k}={r.get(k)}" for k in ("blue", "yellow") if k in r)
        lines.append(f"| {r['score']} | {r['mtime']} | {r['size_kb']}KB | {cols} | "
                     f"{','.join(r['fname_hits'])} | `{r['path']}` |")
    lines += ["\n## Top PDF matches (obras / engenharia)\n",
              "| score | date | pages | keyword hits | path |", "|--:|--|--:|--|--|"]
    for r in pdfs[: args.top]:
        lines.append(f"| {r['score']} | {r['mtime']} | {r['pages']} | "
                     f"{','.join(r['kw_hits'])}{' [SCANNED]' if r['scanned'] else ''} | `{r['path']}` |")
    rep.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[hunt] report → {rep.resolve()}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--preset", default="esquadro", choices=list(PRESETS))
        sp.add_argument("--index", default="found/index.json")
        sp.add_argument("--top", type=int, default=25)
        sp.add_argument("--csv", help="write full ranking to CSV")
        sp.add_argument("--copy-top", type=int, default=0, help="copy top-N hits to --out")
        sp.add_argument("--out", help="dir for --copy-top")

    def scan_opts(sp):
        sp.add_argument("--roots", nargs="*", help="explicit dirs to walk (overrides defaults)")
        sp.add_argument("--drives", nargs="*", help="drive letters for full scan, e.g. C D E")
        sp.add_argument("--quick", action="store_true", help="only common doc/picture folders")
        sp.add_argument("--min-kb", type=int, default=2, help="ignore files smaller than this")
        sp.add_argument("--include-recycle", action="store_true", default=True)

    sp = sub.add_parser("scan"); scan_opts(sp); sp.add_argument("--index", default="found/index.json")
    sp.add_argument("--preset", default="esquadro", choices=list(PRESETS))
    sp.add_argument("--top", type=int, default=25)

    sp = sub.add_parser("images"); common(sp)
    sp.add_argument("--colors", help="override preset colors, e.g. 'yellow,blue'")

    sp = sub.add_parser("pdfs"); common(sp)

    sp = sub.add_parser("verify"); common(sp)
    sp.add_argument("--colors")
    sp.add_argument("--csv-in", help="CSV from `images --csv` (else re-scores now)")
    sp.add_argument("--verify-top", type=int, default=20, help="how many top images to vision-check")

    sp = sub.add_parser("secrets"); scan_opts(sp)
    sp.add_argument("--top", type=int, default=25)
    sp.add_argument("--preset", default="esquadro", choices=list(PRESETS))
    sp.add_argument("--ocr", action="store_true", help="also OCR images LOCALLY (Tesseract) for seeds/passwords")
    sp.add_argument("--reveal", action="store_true", help="print FULL secrets (default: redacted)")
    sp.add_argument("--extract", action="store_true", help="save MetaMask vault blob to --out")
    sp.add_argument("--out", help="dir for extracted vault")

    sp = sub.add_parser("vault")
    sp.add_argument("--extract", action="store_true", help="save the vault blob(s) to --out")
    sp.add_argument("--out", help="dir for extracted vault (default found/vault)")

    sp = sub.add_parser("hunt"); common(sp); scan_opts(sp)
    sp.add_argument("--colors")
    sp.add_argument("--report", help="markdown report path")
    return p


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    Path("found").mkdir(exist_ok=True)
    args = build_parser().parse_args()
    if args.cmd == "scan":
        # give scan the attrs hunt/others expect
        for a in ("roots", "drives", "quick", "min_kb", "include_recycle"):
            if not hasattr(args, a):
                setattr(args, a, None)
        cmd_scan(args)
    elif args.cmd == "images":
        cmd_images(args)
    elif args.cmd == "pdfs":
        cmd_pdfs(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "secrets":
        cmd_secrets(args)
    elif args.cmd == "vault":
        cmd_vault(args)
    elif args.cmd == "hunt":
        cmd_hunt(args)


if __name__ == "__main__":
    main()
