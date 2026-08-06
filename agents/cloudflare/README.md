# cloudflare agent — quickstart

Drives the owner's Cloudflare account (R2, DNS, Workers/Pages, Turnstile, Email Routing, cache)
via the account REST API + the R2 S3 keys. Reads creds from the repo `.env`. **Never** prints
secret values. See [`SKILL.md`](SKILL.md) for the full fleet map, decision matrix, and gotchas.

## Prereqs
- `uv` installed (deps auto-install via PEP-723).
- Repo `.env` has: `ACCOUNT_ID_CLOUDFLARE`, `TOKEN_API_CLOUDFRARE` (note the typo — keep it),
  `ACCESS_KEY_CLOUDFLARE`, `SECRET_ACCESS_KEY_CLOUDFLARE`, `S3_API_ENDPOINT_CLOUDFLARE`. See
  the repo `.env.example`.

## 3 commands

```bash
# 1. Is the token good? (account-owned token → verified at /accounts/{id}/tokens/verify)
uv run agents/cloudflare/cf.py verify

# 2. What's in the account? (zones, R2 buckets + CORS rule counts, workers, pages, turnstile)
uv run agents/cloudflare/cf.py inventory

# 3. Fix R2 CORS SAFELY — GET first, merge yourself, then PUT (PUT replaces the whole ruleset):
uv run agents/cloudflare/cf.py cors-get ania-avatares            # copy the full rules array
#   ...edit into rules.json as {"rules":[ ...kept + new... ]}...
uv run agents/cloudflare/cf.py cors-put ania-avatares rules.json         # preview CURRENT vs NEW
uv run agents/cloudflare/cf.py cors-put ania-avatares rules.json --yes   # apply
```

## Also handy
```bash
uv run agents/cloudflare/cf.py buckets                                   # list R2 buckets
uv run agents/cloudflare/cf.py presign ania-avatares exports/x.ania \
      --content-type application/octet-stream --expires 3600             # presigned PUT + GET urls
uv run agents/cloudflare/cf.py turnstile-list                            # list Turnstile widgets
uv run agents/cloudflare/cf.py purge <zone_id> --files https://site/a.js # cache purge (needs a zone)
```

## Two things that WILL bite you
1. **`cors-put` replaces the entire ruleset.** Always `cors-get` first and keep every rule you
   still need (e.g. `ania-avatares` has a streaming GET/HEAD rule AND an upload PUT rule — keep both).
2. **The R2 S3 keys can't set CORS** (object-scoped → `AccessDenied`). CORS/bucket-admin go through
   the account API token, which `cf.py` uses. The S3 keys are for presigning + object I/O only.
