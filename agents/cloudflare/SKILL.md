---
name: cloudflare
description: >
  Operates the owner's Cloudflare account end-to-end via the account REST API (api.cloudflare.com
  /client/v4) and the R2 S3-compatible API. One account-owned API token with ~all permission groups
  drives it: R2 (buckets, CORS, presigned uploads, public dev URLs, custom domains, lifecycle),
  DNS/zones records, cache purge, Workers + Pages deploys (wrangler), Turnstile widget creation,
  Email Routing rules, Images/Stream, and Zero Trust Access basics. Use when a task says "fix the R2
  CORS", "presign an upload", "add/create a bucket", "the browser upload fails with Failed to fetch",
  "add a DNS record / purge cache", "deploy a Worker or Pages site", "create a Turnstile site", or
  "set up email forwarding". Ships a read-safe CLI (cf.py) that verifies the token, maps the fleet,
  and edits CORS with a mandatory GET-first-then-merge guardrail. It NEVER prints secret values and
  NEVER blind-PUTs a CORS ruleset. Reads creds from the repo .env only.
---

# cloudflare agent — drive the account's Cloudflare fleet safely

You are the hands on this owner's Cloudflare account. The owner minted **one account-owned API
token** (`TOKEN_API_CLOUDFRARE`) carrying essentially every permission group (R2 Storage Write,
DNS, Workers Scripts, Pages, Zero Trust/Access, WAF, Turnstile, Email Routing, Stream, Images, D1,
KV, Queues, AI Gateway, Load Balancers, Rulesets, Cache, Billing Read, …). That token is the Bearer
for `https://api.cloudflare.com/client/v4`. A separate **R2 S3-compatible key pair** exists for
S3-protocol work (presigning, object I/O).

**Two golden rules, learned the hard way (see Gotchas):**
1. `PUT .../r2/buckets/{b}/cors` **REPLACES the whole ruleset**. Never blind-PUT. Always GET current
   rules, merge, then PUT. A blind PUT here once wiped the GET/HEAD streaming rule that obra.vision
   and housestudio players depend on.
2. The R2 **S3-compatible keys are object-scoped** — `PutBucketCors` over the S3 API →
   `AccessDenied`. Do CORS (and all bucket-admin) over the **account REST API** with the token.

## Operating rules (read AGENTS.md "Lost-agent operating rules" first)
- **Target project is the workspace.** When you change a project's Cloudflare wiring (a new bucket,
  a CORS origin, a DNS record, a Pages project), record the concrete facts — bucket name, public
  URL, which origins/methods are in CORS, zone id if any — in that **target project's own brain**
  (Obsidian vault → `wiki/`/`.llm-wiki/` → else `./.cloudflare/`). Generalizable lessons (new API
  quirks, better command shapes) come back into THIS SKILL.md.
- **Secrets discipline (hard, PUBLIC repo).** This repo is public. The token and the R2 keys live
  ONLY in the gitignored `.env`; their NAMES are documented in `.env.example` with no values. Never
  print, echo, log, or paste a token/key value into any file, the wiki, a PDF, chat, or a commit.
  `cf.py` reads `.env` itself and prints results only — never the credentials.

## Env contract (names only — values live in the repo's gitignored `.env`)
| Var | What it is | Used for |
|---|---|---|
| `ACCOUNT_ID_CLOUDFLARE` | account id | path segment `/accounts/{id}/…`; R2 S3 endpoint host |
| `TOKEN_API_CLOUDFRARE` | account-owned API token (**note the typo — do not rename**) | `Authorization: Bearer` for the REST API; also `CLOUDFLARE_API_TOKEN` for wrangler |
| `ACCESS_KEY_CLOUDFLARE` | R2 S3 access key id | boto3/aws presign + object I/O |
| `SECRET_ACCESS_KEY_CLOUDFLARE` | R2 S3 secret access key | boto3/aws presign + object I/O |
| `S3_API_ENDPOINT_CLOUDFLARE` | R2 S3 endpoint `https://<account>.r2.cloudflarestorage.com` | boto3 `endpoint_url` |

For **wrangler**, export `CLOUDFLARE_API_TOKEN=$TOKEN_API_CLOUDFRARE` and
`CLOUDFLARE_ACCOUNT_ID=$ACCOUNT_ID_CLOUDFLARE` in the shell (wrangler reads those exact names).

## Account fleet map (inventoried READ-ONLY on 2026-07-04 — re-run `cf.py inventory` to refresh)

- **Account:** "<your-cloudflare-account>" (id in `CLOUDFLARE_ACCOUNT_ID`). Token status **active**.
- **Zones (DNS):** **NONE.** No domains are managed as Cloudflare zones on this account. So
  `aniamodels.shop`, `housestudio.online`, `obra.vision` are **NOT** Cloudflare-DNS here — their DNS
  lives elsewhere (registrar/other provider); Cloudflare is used for **R2 object storage only**.
  ⇒ DNS-record and cache-purge tasks have **no zone to act on** here today. If the owner later adds a
  domain to Cloudflare, `cf.py inventory` will show a zone id and the DNS/purge rows below light up.
- **R2 buckets (4):**
  | Bucket | Purpose | Public URL / notes |
  |---|---|---|
  | `ania-avatares` | Ania marketplace avatars/exports | dev URL `pub-60575de313174b09925277ad00b59af8.r2.dev`; **2 CORS rules** (see below) |
  | `bucketperola` | (perola project) | 1 CORS rule: `GET` from `*` |
  | `house-studio-storage` | House Studio (housestudio.online) | 1 CORS rule: `GET/HEAD` from `*`, exposes ETag/Content-Length/Content-Type |
  | `obra-vision-storage` | Obra.Vision (obra.vision) | 1 CORS rule (added 2026-07-04): `GET/HEAD` from `https://obra.vision`, `https://*.obra.vision`, localhosts 5173/3000; exposes Content-Length/Content-Type/Accept-Ranges/Content-Range. r2.dev URL disabled → reads via presigned S3 GETs. No PUT rule yet. |
- **Workers:** 1 — `seguranca`.
- **Pages projects:** none.
- **Turnstile widgets:** none created on this account yet.
- **Images / Stream / D1 / KV / Queues:** none inventoried (token can create them if asked).

### `ania-avatares` CORS — the exact live ruleset (PRESERVE BOTH when editing)
```json
{ "rules": [
  { "allowed": { "origins": ["https://obra.vision","https://aniamodels.shop","https://*.aniamodels.shop","https://housestudio.online","https://*.housestudio.online","http://localhost:5173","http://localhost:3000"],
                 "methods": ["GET","HEAD"], "headers": ["*"] },
    "exposeHeaders": ["Content-Length","Content-Type","Accept-Ranges","Content-Range"],
    "maxAgeSeconds": 86400 },
  { "allowed": { "origins": ["https://aniamodels.shop","https://*.aniamodels.shop","http://localhost:5173"],
                 "methods": ["PUT"], "headers": ["*"] },
    "exposeHeaders": ["ETag"], "maxAgeSeconds": 3600 }
] }
```
Rule 1 = **streaming/read** (range requests → the `Content-Range`/`Accept-Ranges` exposeHeaders) used
by the obra.vision / aniamodels / housestudio players. Rule 2 = **direct browser upload** (presigned
PUT from the aniamodels uploader; ETag exposed for multipart). Losing either breaks a live feature.

## The hands: `cf.py` (read-safe; run with `uv`)
```bash
uv run agents/cloudflare/cf.py verify                     # token active? (account-owned verify)
uv run agents/cloudflare/cf.py inventory                  # refresh the fleet map above
uv run agents/cloudflare/cf.py buckets                    # list R2 buckets
uv run agents/cloudflare/cf.py cors-get   <bucket>        # ALWAYS run before editing CORS
uv run agents/cloudflare/cf.py cors-put   <bucket> rules.json --yes   # REPLACES ruleset (guarded)
uv run agents/cloudflare/cf.py presign    <bucket> <key> --content-type image/png [--expires 3600]
uv run agents/cloudflare/cf.py dns-list   <zone_id>       # (no zones today)
uv run agents/cloudflare/cf.py purge      <zone_id> --everything | --files url1,url2
uv run agents/cloudflare/cf.py turnstile-list
```
`cors-put` GETs the current rules, prints CURRENT-vs-NEW, and refuses without `--yes` — but it PUTs
**exactly** the file you give it, so **you** must have merged. `presign` reads the S3 keys and emits
PUT+GET urls; it never prints the keys.

## Decision matrix — task → exact call

Set once per shell for raw calls:
`ACC=$ACCOUNT_ID_CLOUDFLARE ; TOK=$TOKEN_API_CLOUDFRARE ; API=https://api.cloudflare.com/client/v4`

| Task | Exact call |
|---|---|
| **Verify token** | `GET $API/accounts/$ACC/tokens/verify` → expect `result.status:"active"`. (**Account-owned token** — `/user/tokens/verify` returns 1000 "Invalid API Token".) Or `cf.py verify`. |
| **List R2 buckets** | `GET $API/accounts/$ACC/r2/buckets` |
| **Create R2 bucket** | `POST $API/accounts/$ACC/r2/buckets` body `{"name":"<b>","locationHint":"wnam"}` (locationHint optional) |
| **Delete R2 bucket** | `DELETE $API/accounts/$ACC/r2/buckets/<b>` (must be empty) |
| **GET R2 CORS** | `GET $API/accounts/$ACC/r2/buckets/<b>/cors` — **do this first, every time** |
| **PUT R2 CORS** | `PUT $API/accounts/$ACC/r2/buckets/<b>/cors` body `{"rules":[…]}` — **REPLACES all rules**; merge the GET result yourself. Prefer `cf.py cors-put`. **NOT** the S3 `PutBucketCors` (object keys → AccessDenied). |
| **Delete R2 CORS** | `DELETE $API/accounts/$ACC/r2/buckets/<b>/cors` (wipes all — rarely what you want) |
| **R2 lifecycle** | GET/PUT `$API/accounts/$ACC/r2/buckets/<b>/lifecycle` body `{"rules":[{"id":"expire-tmp","enabled":true,"conditions":{"prefix":"tmp/"},"deleteObjectsTransition":{"condition":{"maxAge":604800}}}]}` |
| **R2 public dev URL (r2.dev)** | GET/PUT `$API/accounts/$ACC/r2/buckets/<b>/domains/managed` body `{"enabled":true}` → returns the `<id>.r2.dev` host. (`ania-avatares` already public: `pub-60575…r2.dev`.) |
| **R2 custom domain** | `POST $API/accounts/$ACC/r2/buckets/<b>/domains/custom` body `{"domain":"cdn.example.com","enabled":true}` — requires the domain be a CF zone (none today). |
| **Presign upload/download** | `cf.py presign <b> <key> --content-type <ct>`. Or boto3 directly: `client("s3", endpoint_url=$S3_API_ENDPOINT_CLOUDFLARE, aws_access_key_id=…, aws_secret_access_key=…, region_name="auto")`, `generate_presigned_url("put_object"|"get_object", Params={"Bucket","Key",["ContentType"]}, ExpiresIn=3600)`. Browser PUT **also needs bucket CORS** (PUT + ETag). |
| **DNS: list records** | `GET $API/zones/<zone_id>/dns_records?per_page=100` (need a zone; none today) |
| **DNS: create A/CNAME** | `POST $API/zones/<zone_id>/dns_records` body `{"type":"A","name":"sub.example.com","content":"1.2.3.4","ttl":3600,"proxied":true}` (CNAME: `"type":"CNAME","content":"target."`) |
| **DNS: update / delete** | `PUT`/`PATCH`/`DELETE $API/zones/<zone_id>/dns_records/<record_id>` |
| **Cache purge (all)** | `POST $API/zones/<zone_id>/purge_cache` body `{"purge_everything":true}` |
| **Cache purge (files/hosts/prefixes/tags)** | same endpoint, body `{"files":[…]}` / `{"hosts":[…]}` / `{"prefixes":[…]}` / `{"tags":[…]}` |
| **Create Turnstile widget** | `POST $API/accounts/$ACC/challenges/widgets` body `{"name":"aniamodels-login","domains":["aniamodels.shop","localhost"],"mode":"managed"}` → returns `sitekey` (public) + `secret` (backend-only — write to the TARGET project's `.env`, never here). Verify tokens at `POST https://challenges.cloudflare.com/turnstile/v0/siteverify` `{secret,response,remoteip?}`. (Handoff: the `captcha` agent owns the code/gate; this agent can mint the widget.) |
| **List Turnstile widgets** | `GET $API/accounts/$ACC/challenges/widgets` (or `cf.py turnstile-list`) — sitekeys are public |
| **Email routing: enable** | `POST $API/zones/<zone_id>/email/routing/enable` (zone must be on CF) |
| **Email routing: destination addr** | `POST $API/accounts/$ACC/email/routing/addresses` body `{"email":"me@gmail.com"}` → recipient must click a Cloudflare verify email before it can receive |
| **Email routing: forward rule** | `POST $API/zones/<zone_id>/email/routing/rules` body `{"name":"support","enabled":true,"matchers":[{"type":"literal","field":"to","value":"support@example.com"}],"actions":[{"type":"forward","value":["me@gmail.com"]}]}` |
| **Deploy a Worker** | `cd <worker-dir> && CLOUDFLARE_API_TOKEN=$TOK CLOUDFLARE_ACCOUNT_ID=$ACC npx wrangler deploy` (needs `wrangler.toml`). Logs: `npx wrangler tail <name>`. |
| **Deploy a Pages site** | `CLOUDFLARE_API_TOKEN=$TOK CLOUDFLARE_ACCOUNT_ID=$ACC npx wrangler pages deploy <build-dir> --project-name <name>` (creates the project on first run). |
| **List Workers / Pages** | `GET $API/accounts/$ACC/workers/scripts` · `GET $API/accounts/$ACC/pages/projects` |
| **Images / Stream basics** | Images: `POST $API/accounts/$ACC/images/v1` (multipart upload) · list `GET …/images/v2`. Stream: `POST $API/accounts/$ACC/stream` (tus/direct-upload) · list `GET …/stream`. |
| **Zero Trust / Access app** | `GET/POST $API/accounts/$ACC/access/apps` (list/create an Access application); policies under `…/access/apps/<id>/policies`. |

### Windows-safe raw-call examples (bash + python urllib — like sibling agents)
```bash
# GET current CORS (bash + curl)
curl -s -H "Authorization: Bearer $TOKEN_API_CLOUDFRARE" \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID_CLOUDFLARE/r2/buckets/ania-avatares/cors"
```
```python
# python urllib — no curl needed (Windows-safe). Reads .env, prints result only.
import json, urllib.request
from pathlib import Path
env = {}
for l in Path(".env").read_text(encoding="utf-8").splitlines():
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, _, v = l.partition("="); env[k.strip()] = v.split("#")[0].strip().strip('"').strip("'")
A, T = env["ACCOUNT_ID_CLOUDFLARE"], env["TOKEN_API_CLOUDFRARE"]
def call(method, path, body=None):
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4" + path,
        data=json.dumps(body).encode() if body else None, method=method,
        headers={"Authorization": f"Bearer {T}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())
print(call("GET", f"/accounts/{A}/r2/buckets"))  # never prints T; only results
```

## Workflow — editing R2 CORS (the most common + most dangerous task)
1. `cf.py cors-get <bucket>` → copy the FULL current `rules` array.
2. Build the new ruleset by **adding/modifying** rules on top of the current ones — keep every rule
   you're not deliberately changing (e.g. on `ania-avatares` keep BOTH the streaming rule and the
   upload rule). For a browser direct-upload, ensure a rule with `methods:["PUT"]`,
   `exposeHeaders:["ETag"]`, and the exact browser `origins` (scheme+host+port, e.g.
   `http://localhost:5173`).
3. Save to `rules.json` as `{"rules":[…]}`. Run `cf.py cors-put <bucket> rules.json` (no `--yes`) to
   see CURRENT-vs-NEW; confirm nothing you needed vanished.
4. Re-run with `--yes`. Then `cf.py cors-get <bucket>` to confirm, and test the real browser flow
   (upload / range playback) — CORS is on the bucket globally and takes effect immediately.
5. Record the final ruleset in the target project's brain.

## Gotchas (grow this list every run)
- **CORS PUT is destructive (REPLACE, not merge).** `PUT …/r2/buckets/{b}/cors` overwrites the whole
  ruleset. A blind PUT on `ania-avatares` once wiped the GET/HEAD streaming rule and broke the
  obra.vision / housestudio players until restored. **GET → merge → PUT**, always. `cf.py cors-put`
  shows you the before/after and needs `--yes` for exactly this reason.
- **S3 keys are object-scoped → CORS via S3 API = AccessDenied.** `aws s3api put-bucket-cors` /
  boto3 `put_bucket_cors` fail with `AccessDenied` on these keys. Do bucket-admin (CORS, lifecycle,
  public URL, custom domain) over the **account REST API + token**. The S3 keys are for object I/O
  and **presigning** only.
- **Browser direct-to-R2 PUT needs CORS, not just a presigned URL.** Symptom of missing CORS: an
  instant `TypeError: Failed to fetch` in the browser console (no HTTP status). Fix = a bucket CORS
  rule with `methods:["PUT"]`, the exact page origin, and (for multipart) `exposeHeaders:["ETag"]`.
  Presigning authenticates the request; CORS authorizes the browser to make it.
- **Account-owned token ≠ user token for verify.** `/user/tokens/verify` returns 1000 "Invalid API
  Token" for this token even though it's valid — because it's **account-owned**. Verify at
  `/accounts/{id}/tokens/verify` (→ `status:"active"`). All other account GETs work regardless.
- **No zones on this account.** DNS-record and cache-purge endpoints need a `zone_id`, and there are
  none today (the domains use Cloudflare R2 but external DNS). Don't fabricate a zone id — run
  `cf.py inventory`; if `zones` is empty, tell the owner the domain isn't on Cloudflare and DNS/purge
  can't run until it's added.
- **`obra-vision-storage` read CORS added 2026-07-04** (was: none at all — every browser
  cross-origin read failed). GET/HEAD from obra.vision + subdomains + localhosts, streaming
  exposeHeaders. Still **no PUT rule** — browser direct uploads need one (methods PUT, exact
  origins, exposeHeaders ETag). Full ruleset recorded in
  `diario-de-obra-back-end/wiki/integration-cloudflare-r2.md`.
- **Preflight-verify CORS on the S3 endpoint when r2.dev is disabled.** `curl -X OPTIONS
  https://<account>.r2.cloudflarestorage.com/<bucket>/<key> -H "Origin: …"
  -H "Access-Control-Request-Method: GET"` → expect 204 + `Access-Control-Allow-Origin` echo;
  non-allowed origins get 403. Works unauthenticated — good instant check after `cors-put`.
- **Turnstile secret is backend-only.** The widget `sitekey` is public (ships in the page); the
  `secret` returned on create goes into the TARGET project's gitignored `.env` (never this repo,
  never a `VITE_`/`NEXT_PUBLIC_` var). Hand the wiring to the `captcha` agent.
- **Email routing destination must be verified** by the recipient (they click a CF email) before a
  forward rule delivers; and the sending domain's MX must point to CF Email Routing (only possible if
  the domain is a CF zone).
- **wrangler auth is env-based.** Export `CLOUDFLARE_API_TOKEN` (= `$TOKEN_API_CLOUDFRARE`) and
  `CLOUDFLARE_ACCOUNT_ID`; otherwise wrangler opens an interactive OAuth browser login (hangs in a
  non-interactive agent).
- **R2 presign `region_name` must be `"auto"`** and SigV4; the region is ignored by R2 but boto3
  requires one. `ExpiresIn` max is 604800s (7 days).

## Self-check — before claiming a Cloudflare change is done
- [ ] `cf.py verify` → `status:"active"`.
- [ ] For any CORS edit: GET-then-merge (no rule silently dropped); re-GET confirms; real browser
      flow tested (upload succeeds / range playback works).
- [ ] No token/key VALUE printed, logged, or written to any file, wiki, PDF, or commit.
- [ ] New env var NAMES (if any) are in `.env.example` with a comment; values only in `.env`.
- [ ] Concrete per-project facts (bucket, public URL, CORS origins, zone/record ids) written to the
      **target project's** brain; generalizable quirks folded back into this SKILL.md.

## How the user invokes this agent
> Read `…/agentes_perdidos/agents/cloudflare/SKILL.md`. <task>, e.g.: "add `http://localhost:5173`
> as an allowed PUT origin on `ania-avatares` CORS without dropping the streaming rule", or "give
> `obra-vision-storage` a browser read CORS rule", or "presign a PUT for key `exports/x.ania` on
> `ania-avatares`", or "create a Turnstile managed widget for aniamodels.shop + localhost".
> Use `uv run agents/cloudflare/cf.py …`; GET CORS before any PUT; never print secrets.
