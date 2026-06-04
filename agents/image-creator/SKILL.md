---
name: image-creator
description: >
  Generates images for a project's missing/fallback assets using the best of two
  APIs. Routes TRANSPARENT-background images (logos, mascots, icons, sprites, UI
  frames) to OpenAI gpt-image-1.5, and NORMAL/photographic images (backgrounds,
  hero art, banners, scenes) to Google Gemini "Nano Banana". Reads a project's
  prompts.md, generates each asset, and writes it to the project's expected path
  in the correct format. Use when a user asks to create/fill image assets for a project.
---

# image-creator agent

You create the images a project is waiting on. Typical job: the user opens a session,
points you at THIS skill **and** at a target project's `prompts.md` (or a single prompt),
and says "create these and drop them at the right paths." You decide the provider per
image, run `imagegen.py`, and place each file with the correct extension.

## The two engines (and why the split)

| | OpenAI `gpt-image-1.5` | Gemini `gemini-2.5-flash-image` ("Nano Banana") |
|---|---|---|
| **Transparency (alpha PNG)** | ✅ native (`background="transparent"`) | ❌ none — solid background only |
| Best at | clean isolated subjects, logos, icons, sprites, anything cut-out; strong text rendering | photorealism, scenes, lighting, **iterative editing**, character consistency, multi-image fusion |
| Sizes | 1024², 1536×1024, 1024×1536 | 1K native (2K/4K only on gemini-3 models); rich aspect ratios |
| Cost (≈1024², high) | ~$0.13/img | ~$0.039/img (cheaper) |
| Watermark | none | invisible SynthID on every output |

> ⚠️ `gpt-image-2` (OpenAI's flagship) does **NOT** support transparency — that's why the
> transparent route pins `gpt-image-1.5`. Gemini has **no** alpha at all.

## Decision matrix — pick the provider with these rules

1. **Does the asset need a transparent background?** → **OpenAI** (`--transparent`).
   Tells: prompt says "transparent", "isolated", "cut-out", "for app icon", "sprite",
   "PNG with alpha"; or the asset is a logo / mascot / icon / UI frame / character cutout;
   or the target extension is `.png` AND it overlays other content.
2. **Otherwise it's a normal raster image** → **Gemini** (`--opaque`, the default).
   Tells: backgrounds, hero/landscape art, news banners, textures, photographic scenes,
   anything with a full-bleed background. Cheaper and stronger at photorealism/scenes.
3. **Editing an existing image** (add/change something on a given image)? Pass `--ref`.
   - Need the edit to stay transparent → OpenAI.
   - Photographic edit / relight / add element on opaque art → Gemini (its strength).
4. **`.svg` requested?** Neither API outputs vector. Generate a clean raster (transparent
   PNG via OpenAI at the largest sensible size) and tell the user it must be traced/vectorized
   separately. Never silently save a `.png` as `.svg`.
5. **Format from the project's filename**: `.png` (keep alpha), `.jpg/.jpeg` (opaque, Gemini),
   `.webp` (either). Match exactly what the project expects.

When unsure between the two for a borderline case, prefer the rule above on transparency;
if still ambiguous, ask the user briefly.

## How to run

Use `uv` (auto-installs deps from the script's inline metadata — no venv setup needed):

```bash
# transparent logo -> OpenAI
uv run agents/image-creator/imagegen.py generate \
  --prompt "<full prompt>" --out client/assets/logo.png --transparent --aspect 1:1

# opaque hero background -> Gemini (default)
uv run agents/image-creator/imagegen.py generate \
  --prompt "<full prompt>" --out client/assets/hero.jpg --opaque --aspect 16:9

# edit an existing image (add element), keep it photographic -> Gemini
uv run agents/image-creator/imagegen.py generate \
  --prompt "raise the right arm in a wave" --ref mascote.png --out mascote-aceno.png --opaque

# force a provider / pick a different model
uv run .../imagegen.py generate --prompt "..." --out x.png --provider openai --model gpt-image-1.5
```

Flags: `--transparent|--opaque` (default opaque) · `--provider auto|openai|gemini` (auto =
follow the matrix) · `--aspect 1:1|16:9|9:16|3:4|4:3|...` · `--quality low|medium|high`
(OpenAI) · `--image-size 1K|2K|4K` (Gemini-3 only) · `--ref <img>` (edit) · `--model <id>` ·
`--json` (machine-readable result line).

## Workflow when given a project's prompts.md

1. Read the project's `prompts.md` and any `DESIGN.md` for palette/style. Note the
   "master style suffix" and negative prompt — **append the master style** to each prompt.
2. Build the full asset list: for each, record `{filename, target path, size/aspect, transparent?}`.
   Infer the target path from the project layout (e.g. its assets dir) — confirm with the
   user if the destination isn't obvious.
3. For each asset, apply the **decision matrix**, then run `imagegen.py` writing straight to
   the project's expected path and extension.
4. Report a table: asset → provider/model → path → ok/failed. Re-run failures (safety blocks
   or rate limits) with a tweaked prompt or backoff.
5. Don't burn budget: generate at `--quality high` for finals, but if iterating on a look,
   draft at `low` first.

## Gotchas

- **Aspect ratios**: OpenAI snaps to 1024²/1536×1024/1024×1536; Gemini honors the exact ratio.
- OpenAI image endpoints need **org verification** (403 otherwise). Gemini free tier ≈ 500 req/day.
- Failed/blocked OpenAI prompts still consume quota — fix prompts before retry-storming.
- Model names drift; if a call 404s, override `--model` or update `.env`. Defaults are pinned
  in `imagegen.py` and documented in `.env.example`.
