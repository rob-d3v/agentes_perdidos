---
name: lost-finder
description: >
  Forensic hunter for lost files on a machine. Finds files the user can describe but
  can't locate — even when they were RENAMED, moved into a backup, or dropped in the
  Recycle Bin — by matching on CONTENT, not just filename. Images are matched by a color
  signature (e.g. "yellow logo on a blue background"); PDFs by extracted-text keywords
  (e.g. "esquadro engenharia obra civil"); everything is also scored by filename hits and
  ranked. Use when a user says "I lost a file", "I can't find my old art / logo / PDF",
  "find that document somewhere on my disk", or describes a file by how it looks / what
  it's about rather than its name or path. Also runs a LOCAL-ONLY "secrets mode" to help a
  user recover their OWN lost wallet credentials (MetaMask seed phrase / password / vault):
  BIP39 checksum-validated seed detection, browser vault-blob extraction, optional local OCR.
---

# lost-finder agent

You find files a person describes but lost track of. The trick: people remember **what a
file looks like or is about** ("yellow set-square logo on blue", "a PDF of my dad's
construction jobs") long after they've forgotten its name or folder. So you match on
**content** — image colors and PDF text — which survives renames, moves, and dumps into
random backup folders or the Recycle Bin.

The hands are [`lostfinder.py`](lostfinder.py), run with `uv` (deps auto-install via
PEP-723; no venv). No API keys required for the core hunt.

## How it decides what's a match

| Signal | Used for | How it scores |
|---|---|---|
| **Color signature** | images (png/jpg/jpeg/webp/gif/bmp/tif) | thumbnails each image, classifies pixels into HSV color buckets, scores how strongly the **wanted colors are both present** (geometric mean, +bonus when one color dominates like a background). Transparent pixels are treated as background and ignored. |
| **PDF text keywords** | pdfs | extracts text (first ~25 pages) and counts distinct keyword hits. Flags `[SCANNED]` when there's no extractable text (image-only PDF → needs OCR, see gotchas). |
| **Filename keywords** | both | substring hits in the filename nudge the rank up but never decide alone (the file may be renamed to garbage). |
| **Vision verify** (optional) | top images | sends the top-N color matches to Gemini vision with a yes/no prompt ("is this *the* set-square logo, not a meme/avatar/photo?"). Kills the color stage's false positives. Needs `GEMINI_API_KEY` in repo `.env`. |

A **preset** bundles the color set + keyword sets for one hunt. Two ship built-in:

- **`escritores`** — text-only target for the **"Escritor Fantástico" writing course** (Prof.
  Saymon César; user once called it "Marina Blanc") and any loose creative-writing / literatura
  fantástica docs. No color signature; matched purely by pt-BR keywords across **PDFs AND slide
  decks** (pptx/odp/key) AND writing docs (docx/txt/md/epub) via the new `docs` command. Use this
  to hunt course slides/apostilas, the D.E.H. "Dossiê do Escritor Híbrido" workbook, novel drafts, etc.
- **`esquadro`** — image+pdf target (below).

The `esquadro`
preset targets: a **yellow set-square (esquadro) logo on a blue background** PNG/JPG, plus a
**civil-engineering "obras" PDF** (keywords: esquadro, engenharia, obra, civil, projeto,
planta, orçamento, construção, reforma, CREA, m², …). Edit `PRESETS` in the script to add
new targets — that's the one place that encodes "what we're looking for".

## Commands

```bash
# ALL-IN-ONE — scan + score images + score pdfs + write a markdown report.
# --quick = only the obvious folders (Desktop/Documents/Downloads/Pictures/OneDrive).
uv run agents/lost-finder/lostfinder.py hunt --preset esquadro --quick --copy-top 15

# Full sweep of whole drives (slower; includes Recycle Bin). E is the user's backup drive.
uv run agents/lost-finder/lostfinder.py hunt --preset esquadro --drives C D E --copy-top 20

# Hunt the writing course (text-only preset): scores pdfs + slides (pptx/odp) + docs by pt-BR keywords.
uv run agents/lost-finder/lostfinder.py hunt --preset escritores --drives C D E --copy-top 25
# Just the slide-deck / writing-doc stage from an existing index:
uv run agents/lost-finder/lostfinder.py docs --preset escritores --index found/index.json --copy-top 25

# Or run the stages separately (re-use one index for many scoring passes):
uv run agents/lost-finder/lostfinder.py scan   --drives C D E --index found/index.json
uv run agents/lost-finder/lostfinder.py images --index found/index.json --copy-top 20 --csv found/imgs.csv
uv run agents/lost-finder/lostfinder.py pdfs   --index found/index.json --copy-top 20 --csv found/pdfs.csv
uv run agents/lost-finder/lostfinder.py docs   --index found/index.json --copy-top 20 --csv found/docs.csv

# Tweak the color target without touching code:
uv run agents/lost-finder/lostfinder.py images --colors yellow,blue --index found/index.json

# VISION VERIFY — vision-check the top color matches to drop memes/avatars/photos.
# Re-scores from the index, or feed a CSV from `images --csv`. Needs GEMINI_API_KEY.
uv run agents/lost-finder/lostfinder.py verify --index found/index.json --verify-top 20 --copy-top 10
uv run agents/lost-finder/lostfinder.py verify --csv-in found/imgs.csv --verify-top 30
```

Outputs land under `found/`: `index.json` (the candidate list), a ranked console table +
optional `--csv`, copies of the top hits in `found/images/` and `found/pdfs/` (prefixed
`NN_score_name` so they sort by confidence), and `found/report.md` from `hunt`.

`--copy-top N` is the payoff: it copies the N highest-ranked files into one folder so the
user can **open it and eyeball them** — far faster than chasing paths around the disk.

## Workflow (typical task: "find my lost art + PDF")

1. **Lock the target.** Confirm the description → pick/extend a preset. For the esquadro
   case: colors `yellow,blue`; image exts include jpg (art exports are often jpg too).
2. **Start narrow, then widen.** Run `hunt --quick` first (seconds). If the file isn't in
   the top hits, run the full `--drives C D E` sweep. The user's **E: drive is a backup
   disk** (`E:\backup_2026\…`) — a prime hiding spot for "I lost it years ago" files; always
   include it. OneDrive and the Recycle Bin are included by default.
3. **Read the ranking.** Image hits show `blue=` / `yellow=` fractions and a date; a real
   "yellow logo on blue" usually has high blue (background) + a few % yellow. PDF hits show
   page count, matched keywords, and a `[SCANNED]` flag.
4. **Vision-verify the images.** Color alone yields false positives (a yellow-shirt avatar
   on a blue bg, a yellow+blue meme — both score ~100 on color). Run `verify` to have Gemini
   read the *content* of the top color hits and keep only the real logo. This is the single
   biggest accuracy win for logo hunts.
5. **Eyeball with `--copy-top`.** Open `found/confirmed/` (vision-verified) or `found/images/`
   — confirm the logo by sight. Open the top PDFs to confirm it's the obras doc.
6. **Report** the winners with full original paths and dates so the user can recover them in
   place, and mention near-misses worth a manual look.

## Secrets mode — recover the user's OWN lost wallet credentials

> **Scope & safety (read first).** This mode is for a person recovering **their own**
> wallet on **their own** machine — a legitimate, common need ("I lost my MetaMask password
> /seed from years ago"). Hard rules:
> - **Everything stays local.** Never transmit, paste, upload, or send a seed phrase, private
>   key, password, or vault blob anywhere — not to an API, a gist, a chat, nowhere. The logo
>   `verify` stage may use Gemini (a logo isn't secret); **secret content must not**. That's
>   why image OCR here is **local Tesseract only**, never cloud vision.
> - **Output is redacted by default** (first/last word only). `--reveal` prints full secrets —
>   only when the user asks, and remind them to clear terminal scrollback after.
> - **`found/` is gitignored** and may hold copies of secrets — never commit it.
> - **Do NOT reinstall/reset MetaMask** on the same browser profile while hunting — it
>   overwrites the LevelDB vault and can destroy the only on-disk copy.

What `secrets` finds, in order of value:

1. **BIP39 seed phrases** — scans text/notes/docs/PDFs (and images with `--ocr`) for runs of
   12/18/24 consecutive BIP39 words and **checksum-validates** them. A checksum-valid 12-word
   run is almost certainly a real seed. **A seed fully recovers the wallet — no password
   needed** (reinstall MetaMask → "import using Secret Recovery Phrase").
2. **MetaMask vault blob** — locates the encrypted vault the extension stores on disk
   (`…\Local Extension Settings\nkbihfbeogaeaoehlefnkodbefgpgknn\*.ldb|*.log`) across Chrome,
   Edge, Brave, Vivaldi, Opera profiles. `--extract` saves the `{data,iv,salt}` JSON. Decrypt
   it **offline** at <https://metamask.github.io/vault-decryptor/> with the password; if the
   password is forgotten, feed the blob to `btcrecover` or `hashcat` (modes 26600–26620) with
   password guesses — all offline.
3. **Wallet keyword files** — notes/txt/docx mentioning `metamask`, `senha`, `seed`,
   `recovery phrase`, `carteira`, etc. (pt-BR + en). These are where a written-down password
   most often hides.
4. **Private keys / keystore** — `0x…64-hex` strings near wallet keywords.

```bash
# Locate the MetaMask vault on disk (and save it for the offline decryptor):
uv run agents/lost-finder/lostfinder.py vault --extract --out found/vault

# Full-disk hunt for seed phrases + password notes (redacted output):
uv run agents/lost-finder/lostfinder.py secrets --drives C D E

# Include images (handwritten/screenshot seeds) — LOCAL Tesseract OCR, nothing leaves the PC:
uv run agents/lost-finder/lostfinder.py secrets --drives C D E --ocr

# Reveal full text of a confirmed hit (user asked; clear scrollback after):
uv run agents/lost-finder/lostfinder.py secrets --roots "C:\Users\me\Documents" --reveal
```

**Workflow for "find my lost MetaMask password/seed":** (1) run `vault` first — if the vault is
still on disk and the user *might* recall the password, the official offline decryptor is the
fastest win. (2) Run `secrets --drives C D E` — a recovered **seed phrase beats the password
entirely**. (3) Add `--ocr` if it might be a screenshot/photo. (4) Search the E: backup drive
especially (old files). (5) If only the vault is found and the password is truly lost, hand the
extracted blob to `btcrecover`/`hashcat` with the user's likely password patterns — offline.

## Gotchas

- **Renamed files are the whole point** — never trust filename alone; content score leads,
  filename only breaks ties.
- **Scanned PDFs** (photos of documents, common for construction paperwork) have no text →
  they show `[SCANNED]` and score low on keywords. If the target PDF might be scanned, rank
  by filename + date instead, or add an OCR pass (`pytesseract` + `pdf2image`) before
  keyword scoring. Engineering "obras" PDFs are frequently scanned — keep this in mind.
- **A full multi-drive scan is I/O heavy.** System dirs (`Windows`, `Program Files`,
  `node_modules`, `$WINDOWS.~BT`, …) are pruned automatically; `--min-kb` drops tiny
  icon/sprite noise (default 2 KB). Start `--quick`, escalate only if needed.
- **Color tuning:** if too many false positives, the wanted colors may be too loose — a
  logo-on-background match wants *both* colors present, not just one. Adjust `COLOR_BUCKETS`
  thresholds or pass a tighter `--colors`. Lighting/JPEG artifacts shift hues slightly; the
  buckets already allow some slack.
- **Recycle Bin** files keep cryptic `$R…` names but real content — content matching still
  finds them. Recover via the Recycle Bin UI, not by copying the `$R` file.
- **Core hunt needs no API keys** (local Pillow + pypdf). The optional `verify` stage uses
  the repo's `GEMINI_API_KEY` (model override: `GEMINI_VISION_MODEL`, default
  `gemini-2.5-flash`). For a *logo* hunt, run it — color matching can't tell a set-square
  from a donkey meme; vision can. A few cents of API for the top ~20 candidates.
