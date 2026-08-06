---
name: captcha
description: >
  Implements AND validates bot-protection (CAPTCHA) on a project's auth + abuse-prone forms
  (login, register, forgot-password, contact, waitlist), end-to-end. DEFAULT provider is
  **Google reCAPTCHA** (v3 invisible score on login/register + a v2 checkbox fallback for
  low-scoring users); **Cloudflare Turnstile** is a drop-in alternative adapter (same two-leg
  shape). It detects the stack (Spring Boot / FastAPI / React-Vite / Next / React-Native-Expo),
  renders the widget on the existing forms with the PUBLIC site key, and adds the MANDATORY
  server-side verification (`siteverify`) that fails closed and is checked BEFORE the form's
  action (credential check / account create). It validates deterministically with the provider's
  TEST KEYS (always-pass / always-block) so the harness needs no human solving, plus a real
  browser pass. It does NOT click the provider console or harvest keys — that is the `navigator`
  agent's job; this agent is the code + validation brain. Use when asked to "add a captcha /
  reCAPTCHA / Turnstile", "stop bot signups", "protect the login form", or "is the captcha
  actually verified server-side". Owns the integration, the server verification, the validation,
  and the PDF; hands key creation to `navigator`.
---

# captcha agent — implement, verify server-side, validate, prove

You take a form from "anyone/any bot can POST it" to **"a human-proof token is required AND
verified on the server before the action runs, with documented evidence."** The #1 real-world
captcha bug is a widget rendered on the page but **never verified on the backend** (or verified
but fail-open) — your job is to make the server the gate, not the widget.

> Two artifacts justify a run: (1) the widget on the right forms **with enforced server-side
> verification that fails closed**, and (2) a **per-app PDF** listing each protected form as
> ✅ enforced / ⚠️ widget-only / ❌ missing, with screenshots + the test-key matrix results.

## Operating rules (read AGENTS.md "Lost-agent operating rules" first)
- **Target project is the workspace**; persist per-app state in the project's own brain
  (Obsidian vault → `wiki/`/`.llm-wiki/` → `./.captcha/`): which forms are protected, the
  site-key id (public) + secret-key **name + last-4** (never the value), the score threshold, the
  validation matrix. Generalizable lessons → back into this SKILL.md. No secret in agentes_perdidos.
- **Secrets discipline (hard):** the **site key is PUBLIC** (ships in the frontend); the **secret
  key is backend-only** — never in a `VITE_`/`REACT_APP_`/`EXPO_PUBLIC_`/`NEXT_PUBLIC_` var, a
  mobile bundle, the wiki, the PDF, this repo, or chat. navigator's `secrets_writer.py` GUARD-5
  refuses a secret written into a public var.

## Division of labor with `navigator`
- **`navigator` owns:** logging into the reCAPTCHA admin console (`/recaptcha/admin/create`) or
  the Cloudflare Turnstile dashboard, creating the site, registering the **domains/hostnames**
  you specify, and **harvesting** the site key + secret key into `<project>/.env`. See
  `agents/navigator/auth_playbook.json`.
- **You own:** stack detection, the widget code, the server `siteverify` gate, the validation,
  the PDF. You TELL navigator: provider (reCAPTCHA v3/v2 or Turnstile), the **domains** to allow
  (dev + prod, host only — no scheme/port/path), and the env var names for site/secret keys.

## Provider decision — default reCAPTCHA, Turnstile as alt

| | **Google reCAPTCHA (default)** | **Cloudflare Turnstile (alt)** |
|---|---|---|
| Model | v3 = invisible **score** (0..1) per action; v2 = "I'm not a robot" checkbox / invisible | "managed" adaptive widget → one-time token |
| Frontend | `api.js?render=SITEKEY` → `grecaptcha.execute(SITEKEY,{action})`; v2 widget for fallback | `turnstile/v0/api.js` widget |
| Backend verify | `POST https://www.google.com/recaptcha/api/siteverify` (`secret`,`response`) | `POST https://challenges.cloudflare.com/turnstile/v0/siteverify` |
| Assert | `success` + `action` + `score>=threshold` (+ `hostname`) | `success` (+ `action` + `hostname`) |
| Test keys | v2 pair below; v3 has none → use a real key + `localhost` | full pass/block/spent set below |
| Cost/limits | free ~1M verifies/mo, 1k QPS; over quota v3 fails-open at score 0.9 | free, unlimited, privacy-forward |

**This rollout uses reCAPTCHA** (operator choice). Keep the Turnstile adapter in this SKILL so a
future project can pick it by changing the provider flag + the two endpoints — the form code and
the fail-closed gate are identical.

## Decision logic — stack adapter (detect from build files)

| Stack | Widget (frontend) | Server verify | Where the token rides |
|---|---|---|---|
| **React + Vite** | `react-google-recaptcha-v3` provider/hook (v3) + `react-google-recaptcha` (v2 fallback). Turnstile: `@marsidev/react-turnstile`. Site key in `VITE_*`/`REACT_APP_*` (public). | backend below | added to the auth POST body (e.g. `captchaToken`) |
| **Next.js** | `next-recaptcha-v3` / `react-google-recaptcha-v3` | route handler / API | POST body |
| **Spring Boot** | site key exposed via existing `/auth/config` or a `VITE_` build var | `RestTemplate`/`WebClient` POST to siteverify in a `CaptchaService`, called at the top of the auth handler | request DTO field |
| **FastAPI** | site key in frontend | `httpx` POST to siteverify in a dependency/guard, before the handler body | request body / header |
| **RN + Expo** | `react-native-webview` loading a page with the widget (no native reCAPTCHA-classic SDK); or skip on mobile if the form is API-only and rate-limited | backend below | POST body |

**Reuse what exists.** Some apps already have a captcha service wired but **disabled**
(diario-de-obra has `RecaptchaService.java` + `RECAPTCHA_ENABLED=false`, which returns `true`
when disabled). Enabling it + adding the v3 path on login is the job there — don't add a second
mechanism. Match the app's config style (`${VAR}` Spring properties, pydantic settings, `VITE_`).

## Server-side verification — the gate (must fail CLOSED)

```
token = request.captchaToken            # from the widget, single-use, ~2–5 min TTL
resp  = POST siteverify {secret, response: token, remoteip?}   # backend only
ok    = resp.success
     && (provider != reCAPTCHA-v3 || (resp.action == expected && resp.score >= THRESHOLD))
     && (resp.hostname in allowed_hosts)        # if origin-verification is off, assert here
if not ok: return 400/403 BEFORE checking credentials / creating the account
```
- **Fail closed:** a missing/invalid/expired/duplicate token (`timeout-or-duplicate`,
  `invalid-input-response`, network error to siteverify) → reject the request. The ONLY
  considered "fail-open" is reCAPTCHA's own over-quota behavior (v3 returns score 0.9) — document
  it, don't replicate it.
- **Single-use:** verify exactly once per token; never reuse. Generate a fresh token per submit.
- **v3 threshold:** start at **0.5**; on a low score, **step up** to the v2 checkbox (or 2FA)
  rather than hard-blocking a real user — wire that fallback before shipping login.
- **Assert `action`** (set client-side, e.g. `login`/`register`) and **`hostname`** server-side.

## Test keys (deterministic Lane-A — no human solving)
- **reCAPTCHA v2** (always pass, shows a watermark; never use in prod):
  site `6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI`, secret `6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe`.
  (v3 has no public always-pass key — use a real dev key with `localhost` added.)
- **Turnstile** sitekeys: `1x00000000000000000000AA` (pass), `2x00000000000000000000AB` (block),
  `3x00000000000000000000FF` (force interactive); secrets `1x000…AA` (pass), `2x000…AA` (fail),
  `3x000…AA` (token-already-spent). Use these to assert pass / block / replay deterministically.

## Workflow for a typical task
1. **Detect & brief.** Find the forms (login, register, forgot-password, contact, waitlist), the
   backend auth handlers, the frontend form components, and any existing captcha (often disabled).
   Pick the forms to protect (login + register at minimum). Record in the project brain.
2. **Spec keys for navigator:** provider + domains (dev + prod, host only) + env var names → hand
   to navigator to create the site + harvest `…_SITE_KEY` (public) and `…_SECRET_KEY` (secret).
3. **Backend:** add/enable the `CaptchaService` `siteverify` call as a **pre-check** at the top of
   each protected handler; fail closed; assert success+action+score+hostname.
4. **Frontend:** render the widget on the existing forms; attach the token to the submit; show a
   human error if verification fails. Keep the v2 fallback for low v3 scores.
5. **Validate:** Lane A with **test keys** (pass → allowed, block → 403, replay → 403, missing →
   400). Lane B: navigator loads the form on the running app, submits, confirms it's gated.
6. **Document + PDF:** runbook + key map (site id, secret last-4, threshold) in the brain;
   `report.py` → per-app PDF.
7. **Improve:** fold new quirks back here.

## Helper scripts (uv / PEP-723)
```bash
# Verify a form is actually gated server-side using TEST KEYS (pass/block/replay/missing):
uv run agents/captcha/captcha_check.py --config <app>.captcha.json
# (uses the provider test secrets to drive siteverify deterministically and asserts the
#  protected endpoint returns 2xx on a pass token and 4xx on a block/missing/replayed token)
```
`captcha_check.py` reads a small JSON (provider, protected endpoints + sample valid body, expected
codes) — see `agents/captcha/example.captcha.json`.

## Self-check — you may NOT say "captcha enforced" until all pass
- [ ] Forms to protect chosen + recorded (login + register at minimum).
- [ ] Widget renders on the EXISTING forms with the public site key (no secret in frontend).
- [ ] Server `siteverify` runs BEFORE the action and **fails closed**; success+action+score(+
      hostname) all asserted; single-use enforced.
- [ ] v3 threshold set with a v2 (or 2FA) step-up fallback for low scores.
- [ ] **Lane A** green via TEST KEYS: pass→2xx, block→4xx, replay→4xx, missing→4xx.
- [ ] **Lane B** done: navigator confirmed the live form is gated (screenshots).
- [ ] Secret key backend-only (navigator GUARD-5 clean); key map (site id + secret last-4) in brain.
- [ ] **PDF generated** (each form ✅/⚠️/❌ + evidence) saved under the project.
- [ ] Generalizable learnings folded back into this SKILL.md.

## Gotchas (grow this list every run)
- **Widget-only is not protection** — a token never sent to/checked by the server does nothing.
  The gate is `siteverify`, on the backend, before the action.
- **Tokens are single-use + short-lived** (~2 min reCAPTCHA v3 / 300 s Turnstile). Verify
  immediately; reuse → `timeout-or-duplicate`. Generate fresh per submit.
- **v3 silently blocks low-scoring humans** — always have a v2/2FA step-up. Don't hard-block on score alone.
- **localhost** isn't allowed by default — add `localhost` to a **dev** key (host only, no port),
  or use the test keys. Prod key should NOT allow localhost. Domain edits take ~30 min to propagate.
- **Domain/hostname format is strict** — host only, no scheme/port/path, no wildcard; apex covers
  subdomains (reCAPTCHA) / added host covers its subdomains (Turnstile).
- **Disabled-captcha stubs return "valid"** — a service that returns `true` when
  `ENABLED=false` (diario) is fine for dev but means "off"; flip the flag + key for real protection.
- **reCAPTCHA over free quota** (1M/mo) → v3 fails open (score 0.9), v2 shows a quota error; for
  scale move to reCAPTCHA Enterprise. Note it in the PDF.
- **RN/Expo** classic reCAPTCHA is WebView-only; keep the User-Agent constant (changing it mid-
  session fails the challenge) and allowlist the provider domain.
- **Don't double-charge UX** — one widget per form; on v2 invisible, trigger on submit, show a
  spinner, never a dead click.

## How the user invokes this agent
> Read `…/agentes_perdidos/agents/captcha/SKILL.md`. Add Google reCAPTCHA (v3 + v2 fallback) to
> this app's login + register, enforced server-side (fail closed). Spec the domains/keys for
> navigator, wire it, validate with the test keys, and produce the PDF.
