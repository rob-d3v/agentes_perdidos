---
title: remodeling agent
type: entity
created: 2026-06-14
updated: 2026-06-14
sources: [agents/remodeling/SKILL.md]
tags: [agent, remodeling, identity, anti-fake]
---

Remodels an existing app/site so it reflects the **real, verifiable identity** of its true owner instead of placeholder/fake persona content. Given a project + the owner's name, city, and profession, it:

1. **Deep-researches** the real person on the web with geo-anchored sub-agent searches (beating homonyms; drives official registries via a browser when needed).
2. **Rewrites all persona copy** — name, credentials, bio, stats, testimonials, contacts, social — keeping only what is sourced and turning everything unverified into `@em_breve` placeholders.
3. **Face-swaps** the images showing the person to their real face (via [[image-creator]]) while preserving original pose/clothes/lighting.
4. **Publishes assets** (via [[bucket]] if the project uses object storage) and records a sourced dossier in the target project's own brain (resumable).

## Golden rule — zero fabrication
Each identity fact lands in one bucket:
| Bucket | Meaning | Action |
|---|---|---|
| **CONFIRMADO** | backed by a citable source (registry, owner material, geo-matched page) | may go on site; record source |
| **INCERTO** | plausible but not geo-confirmed (possible homonym) | do not publish; keep `@em_breve` |
| **CONTRADITÓRIO** | conflicting people / wrong city/UF | discard; list under "discarded" |

Never invents a credential, number, year, quote, client, or statistic. **Changes content, never layout/structure.**

## Key files
- `agents/remodeling/SKILL.md` — brain + anti-fake rule.

See [[lost-agent-rule]] · [[agentes-perdidos]].
