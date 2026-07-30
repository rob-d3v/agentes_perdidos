---
title: image-creator agent
type: entity
created: 2026-06-14
updated: 2026-07-30
sources: [agents/image-creator/SKILL.md]
tags: [agent, image-creator, assets]
---

Generates a project's missing/fallback **image and video assets** across three APIs with automatic fallback. Reads a project's `prompts.md`, generates each asset, writes it to the expected path in the correct format, and logs estimated spend.

## Provider routing
| Asset | Engine | Why |
|---|---|---|
| **Transparent** (logos, mascots, icons, sprites, UI frames) | OpenAI `gpt-image-1.5` | only one with native alpha PNG (`background="transparent"`); strong text rendering |
| **Normal / photographic** (backgrounds, hero art, scenes) | Gemini `gemini-2.5-flash-image` ("Nano Banana") | cheapest (~$0.039/img), photorealism, iterative editing, character consistency |
| **Video** (image→video, text→video) | Kling AI | only video engine (~$0.07–0.14/sec) |

> `gpt-image-2` does NOT support transparency — that's why the transparent route pins `gpt-image-1.5`. Gemini and Kling have no alpha at all.

`--provider auto` (default) picks a capability-ordered chain and falls through on missing key / failure.

**Multi-image fusion / face-swap** (new 2026-07): `--ref` is repeatable — pass it twice for a face-swap (first ref = original image whose pose/clothes/lighting to keep, second ref = the real person's face). Works on OpenAI (keeps alpha) and Gemini (photoreal); this is the primitive [[remodeling]] uses.

## Key files
- `agents/image-creator/SKILL.md` — brain + provider matrix.
- `agents/image-creator/imagegen.py` — the hands (run via [[uv]]).
- Keys: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `KLING_ACCESS_KEY`, `KLING_SECRET_KEY`.

Used by [[design-reviewer]] (asset spec) and [[remodeling]] (face-swap). See [[agentes-perdidos]].
