---
title: cloudflare agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/cloudflare/SKILL.md]
tags: [agent, cloudflare, r2, dns, workers, turnstile, cors]
---

Operates the owner's whole **Cloudflare account** end-to-end via the account REST API (`api.cloudflare.com/client/v4`) + the R2 S3-compatible API: R2 buckets / CORS / presigned uploads / public URLs / lifecycle, DNS records, cache purge, Workers + Pages deploys (wrangler), Turnstile widget creation, Email Routing, Images/Stream, Zero Trust basics.

## Two golden rules (learned the hard way)
1. `PUT .../r2/buckets/{b}/cors` **replaces the whole ruleset** — never blind-PUT. Always GET current rules, merge, then PUT (a blind PUT once wiped the GET/HEAD streaming rule obra.vision and housestudio players depend on). `cf.py` enforces this GET-first-then-merge guardrail.
2. The R2 **S3-compatible keys are object-scoped** — `PutBucketCors` over the S3 API returns `AccessDenied`. All bucket-admin (CORS included) goes over the **account REST API** with the token; the S3 keys are only for presigning + object I/O.

## Env contract (names only; values in gitignored `.env`)
`ACCOUNT_ID_CLOUDFLARE` · `TOKEN_API_CLOUDFRARE` (account-owned Bearer token — **the typo in the name is intentional, keep it exact**) · `ACCESS_KEY_CLOUDFLARE` + `SECRET_ACCESS_KEY_CLOUDFLARE` (R2 S3 pair) · `S3_API_ENDPOINT_CLOUDFLARE`. wrangler reads `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`, exported from those at runtime.

## Relations
Complements [[bucket]] (which offloads a project's assets *to* R2/B2 — cloudflare owns the account plumbing under it), can create Turnstile widgets for [[captcha]]'s alternative path, and records per-project wiring facts (bucket names, CORS origins, zone ids) in the **target project's** brain per [[lost-agent-rule]]. `cf.py` never prints secret values.

Key files: `agents/cloudflare/{SKILL.md,cf.py}` (run via [[uv]]). See [[agentes-perdidos]].
