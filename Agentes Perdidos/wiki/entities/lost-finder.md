---
title: lost-finder agent
type: entity
created: 2026-06-14
updated: 2026-07-30
sources: [agents/lost-finder/SKILL.md]
tags: [agent, lost-finder, forensics]
---

Forensic hunter for lost files on a machine. Finds files the user can describe but can't locate — even when **renamed**, moved to a backup, or in the Recycle Bin — by matching on **content**, not just filename.

## How it decides a match
| Signal | Used for | Scoring |
|---|---|---|
| **Color signature** | images (png/jpg/webp/gif/bmp/tif) | thumbnails + HSV color buckets; scores how strongly wanted colors are both present (geometric mean + dominance bonus); transparent pixels ignored as background |
| **PDF text keywords** | pdfs | extracts text (first ~25 pages), counts distinct keyword hits; flags `[SCANNED]` when no extractable text (needs OCR) |
| **Filename keywords** | both | substring hits nudge rank but never decide alone (file may be renamed to garbage) |
| **Vision verify** (optional) | top images | sends top-N to Gemini vision with a yes/no prompt to kill color-stage false positives; needs `GEMINI_API_KEY` |

A **preset** bundles the color set + keyword sets for one hunt. Two ship built-in (edit `PRESETS` in the script to add more):
- **`esquadro`** — image+pdf target: yellow set-square logo on blue background + civil-engineering "obras" PDF keywords.
- **`escritores`** (new 2026-07) — text-only target for the "Escritor Fantástico" writing course and loose creative-writing docs; no color signature, matched purely by pt-BR keywords across PDFs **and slide decks (pptx/odp/key) and writing docs (docx/txt/md/epub)** via the new `docs` command/stage (`lostfinder.py docs --index ... --copy-top N`).

Matches are ranked and copied into one folder to eyeball.

## Secrets mode (local-only)
Helps a user recover their **own** lost wallet credentials: BIP39 checksum-validated seed detection, MetaMask vault-blob extraction, optional local OCR. Runs locally, no upload.

## Key files
- `agents/lost-finder/SKILL.md` — brain + match logic.
- `agents/lost-finder/lostfinder.py` — the hands (run via [[uv]]); no API keys for the core hunt.

See [[agentes-perdidos]].
