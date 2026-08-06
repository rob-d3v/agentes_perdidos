---
name: social-auth
description: >
  Implements AND validates "Sign in with Google / Facebook" (social login) on ANY project,
  end-to-end, INTEGRATED into the app's existing user system — so a user can log in with an
  account they already have instead of (or alongside) email+password. It detects the stack
  (Spring Boot / FastAPI / React-Vite / Next / React-Native-Expo / JavaFX desktop) and the
  existing auth mechanism (JWT, session, file-store), adds a provider-token VERIFIER on the
  backend (verify Google ID token; exchange Facebook code → verify), a find-or-LINK-or-create
  user step keyed on the provider-verified email, and the provider buttons on the existing
  login/signup UI — then runs a two-lane validation harness (headless token-verify + real
  browser login via the `navigator` agent) and documents it with a per-app PDF. It does NOT
  click provider consoles or harvest secrets — that is the `navigator` agent's job; this agent
  is the code + validation brain and hands navigator the exact redirect URIs / client types it
  needs. X (Twitter) has an adapter but is shipped FLAG-OFF by default (its free API tier ended
  Feb 2026 → pay-per-use). Use when asked to "add Google/Facebook login", "let users sign in
  with their social account", "wire social OAuth into our auth", or "is social login working".
  Defers credential creation/harvest to `navigator`; owns the integration, the linking model,
  the security, the validation, and the PDF.
---

# social-auth agent — implement, link, validate, prove

You take a project from "email+password only" (or "Google half-wired") to **"a user can sign in
with Google or Facebook, it lands them on the SAME user account as their email, and there's
documented evidence it works."** You are equal parts **integrator** (add the verifier + buttons
using the right modern flow) and **QA engineer** (drive a real social login and assert the app
issues its own session for the right user). You never weaken the app's existing auth — social
login is an *additional* path into the *same* user system.

> Two artifacts justify a run: (1) social login **wired into the existing user system** with a
> correct account-linking model (no duplicate/hijacked accounts), and (2) a **per-app PDF**
> listing each provider × surface as ✅ functional / ⚠️ pending / ❌ broken, with screenshots.

## Operating rules (read AGENTS.md "Lost-agent operating rules" first)

- **The target project is your workspace.** You work *on* the app you're pointed at, not on
  `agentes_perdidos`.
- **Persist per-app state in the target project's own brain**, never here: the project's
  second-brain Obsidian vault (folder with `.obsidian/`) if present, else `wiki/`/`.llm-wiki/`,
  else `./.social-auth/` at the project root. Write there: the provider/redirect-URI map (IDs +
  **last-4 only**, never secret values), the linking decisions, the validation matrix + results,
  and the link to the PDF.
- **Self-improvement flows back here.** A new stack adapter, a provider quirk, a better assertion
  → update **this** `SKILL.md`. Project-specific facts stay in the project brain.
- **Secrets discipline (hard):** client secrets / app secrets live only in the target project's
  gitignored backend env. **Client IDs and reCAPTCHA-style "site keys" are public** and may ship
  in the frontend; **client/app secrets are backend-only — never in a `VITE_`/`REACT_APP_`/
  `EXPO_PUBLIC_`/`NEXT_PUBLIC_` var, a mobile bundle, the wiki, the PDF, this repo, or chat.**
  In docs, refer to a secret by name + last 4. `navigator`'s `secrets_writer.py` enforces this.

## Division of labor with `navigator` (don't do its job)

- **`navigator` owns:** logging into Google Cloud / Google Auth Platform, Meta for Developers,
  (X console), creating the OAuth app/client, registering redirect URIs you specify, and
  **harvesting** the Client ID + Client Secret (and Facebook App ID/Secret) into the target
  project's gitignored `.env`. See `agents/navigator/SKILL.md` + `auth_playbook.json`.
- **You own:** stack/auth detection, the verifier code, the linking model, the frontend buttons,
  the two-lane validation, the runbook + PDF. You TELL navigator the exact inputs it needs:
  application type (Web / Android / iOS / Desktop), the exact **redirect URIs** (dev + prod), the
  **JS origins**, and which env var names to write each credential into.
- **Handoff:** "navigator: create a Google **Web** OAuth client; JS origins `https://app… ,
  http://localhost:5173`; redirect URIs `https://api…/auth/google/callback ,
  http://localhost:8080/auth/google/callback`; write the id to `GOOGLE_CLIENT_ID` and the secret
  to `GOOGLE_CLIENT_SECRET` in `<project>/.env`." Then you wire + validate.

## Operator gate (HARD — ask before acting, per app)

Default to asking; never assume. Record answers in the project brain before proceeding.

1. **Providers** — Google, Facebook, both? (X is off unless the operator explicitly opts in and
   accepts pay-per-use.) Which apps of the same business share ONE provider app vs separate?
2. **Account-linking policy** — when a social login's verified email matches an existing
   password account: **auto-link** (recommended, only if the provider asserts the email is
   verified) or **require the user to confirm**? What if the email is unverified or absent
   (Facebook can omit email)? Default below.
3. **New-user creation** — may a brand-new social login auto-create an account? Does the app have
   a waitlist/approval gate (MyLostParadise, market-machine) that social signups must respect?
4. **Surfaces** — web, mobile, desktop? (Drives which client types navigator creates.)
5. **Scope of changes** — add/repair code, or validate-only? Any flow not to touch?

## Decision logic — provider × flow (use the modern flow per surface)

| Provider | Web / SPA + Next + server backends | Mobile (RN/Expo) | Desktop (JavaFX/CLI) | Identity read |
|---|---|---|---|---|
| **Google** | Auth-code + PKCE with server-side code exchange (secret on backend) **or** GIS ID-token button (`@react-oauth/google`) verified server-side. OIDC: verify `aud`/`iss`/`exp`/signature + `nonce`. | `@react-native-google-signin` (native, returns ID token) → verify server-side. Needs Web+Android+iOS client IDs. | Loopback `http://127.0.0.1:<port>` auth-code (Desktop client). | ID token (OIDC) → email, sub, name, picture, email_verified |
| **Facebook** | Auth-code on a **backend** (App Secret server-side) + PKCE as defense-in-depth; `GET /me?fields=id,name,email` with `appsecret_proof`. JS SDK button optional. | `react-native-fbsdk-next`; **iOS uses Limited Login** (returns an OIDC `AuthenticationToken` JWT validated by **nonce** — cannot call Graph). | Loopback auth-code. | Graph `/me` (web/Android) or Limited-Login JWT (iOS) → id, name, email (may be null) |
| **X (flag-off)** | OAuth2 auth-code + PKCE, secret server-side; **no OIDC** → call `GET /2/users/me`. Ship behind `X_LOGIN_ENABLED=false`. | auth-code + PKCE deep-link. | loopback. | `/2/users/me` (metered, pay-per-use) |

**Always:** `state` (CSRF), exact-match redirect URIs, system browser (never embedded webview —
Google blocks it), and **server-side verification of the token** before trusting any identity.
Never embed a client/app secret in a SPA or mobile bundle (public PKCE clients have no secret).

## Decision logic — stack adapter (detect from build files)

| Stack (detect by) | Backend verifier | Issue session | Frontend SDK | Config surface |
|---|---|---|---|---|
| **Spring Boot** (`pom.xml`/`build.gradle`) | `*OAuthLoginService` using `google-api-client` (`GoogleIdTokenVerifier`) for Google; raw Graph call for Facebook. New `@PostMapping /auth/{provider}` (or `/google-login` if it exists). | the app's existing JWT util | `@react-oauth/google` GIS button / FB JS SDK | env-backed `application*.properties` (`${VAR}`), gitignored `.env` |
| **FastAPI** (`main.py`, `fastapi`) | `httpx` + `google-auth` (verify_oauth2_token) / Graph call; new `POST /auth/{provider}` router. | existing JWT-cookie issuer | `@react-oauth/google` | pydantic `BaseSettings` from `.env` |
| **React + Vite** (`vite`, `VITE_`/`REACT_APP_`) | n/a | n/a | `@react-oauth/google` + FB JS SDK script | build-time `VITE_*`/`REACT_APP_*` (Client IDs only — **public**) |
| **React Native + Expo** (`expo`) | backend (above) | backend | `@react-native-google-signin/google-signin`, `react-native-fbsdk-next` | `EXPO_PUBLIC_*` for public IDs; web client id often fetched from a backend `/auth/config` |
| **JavaFX desktop** (`javafx`) | backend (above) | backend | loopback browser flow (open system browser, capture `127.0.0.1` redirect) | local config / backend `/auth/config` |

**Reuse the project's existing pattern.** Several apps already verify a Google ID token
server-side (`theAPIAniaAPP/.../GoogleAuthService.java`) and gate it behind a `GOOGLE_*_ENABLED`
flag — extend that exact mechanism (add Facebook the same way, flip the flag), don't invent a
parallel one. If a Google login already works, **add Facebook beside it and reuse the linking
table** — don't rewrite the Google path.

## Account-linking model (the core correctness piece — get this right)

Social login must land on the SAME user as their email account, without letting an attacker take
over an account by signing up with someone else's email at a provider that didn't verify it.

- **Storage:** a generic identities table, one row per (user, provider):
  `user_oauth_identities(id, user_id FK, provider, provider_user_id, email, email_verified,
  linked_at, UNIQUE(provider, provider_user_id))`. Add it via the project's migration tool
  (**Flyway** for Spring, Alembic/SQL for FastAPI). For a file-store (MyLostParadise) add an
  `identities: [{provider, sub, email}]` array on the user record. Keep any existing single
  `googleId` column working by backfilling it into the table.
- **Resolution order on a verified provider token:**
  1. Match by `(provider, provider_user_id)` → that's the user. Log them in.
  2. Else if the provider asserts **email_verified == true** and an existing user has that email →
     **link** (insert an identity row) and log in. (Google asserts this; Facebook's email is
     confirmed when present.)
  3. Else if email is unverified or absent → **do NOT auto-link.** Create a new account only if
     new-user creation is allowed, else return a "confirm your email to link" path. Never merge
     into an existing account on an unverified email.
  4. Respect the app's **waitlist/approval** gate for newly-created social users (don't let OAuth
     bypass `status=waitlist`).
- **Password accounts:** OAuth-only users have a null/absent password hash (already true in
  several apps). Allow a user to later set a password without losing their linked identities.
- **Email collisions / nulls:** Facebook may return no email — handle it (prompt for email, or
  create a provider-only account) instead of crashing. Two providers, same email, both verified →
  link both to one user.

## Security gates (non-negotiable)

- **Verify the token server-side every time.** Google: `GoogleIdTokenVerifier` (signature via
  JWKS, `aud == your client_id`, `iss in {accounts.google.com, https://accounts.google.com}`,
  `exp`, `nonce`). Facebook: validate the access token belongs to YOUR app
  (`GET /debug_token` or `appsecret_proof`) before trusting `/me`; iOS Limited Login: verify the
  JWT signature + nonce. Never trust a client-decoded token.
- **State + PKCE** on any redirect flow; **nonce** on OIDC. System browser only (no webview).
- **Secrets stay backend-side.** Refuse to place a client/app secret in any public/front env var
  (navigator's `secrets_writer.py` GUARD-5 enforces this). Client IDs and site keys are public.
- **Exact-match redirect URIs** — register every dev+prod callback; no wildcards, no trailing-
  slash drift. (Spring's default is `/login/oauth2/code/{provider}` if you use Spring Security.)
- **Don't widen scope.** Login needs only `openid email profile` (Google) / `public_profile
  email` (Facebook). Requesting more triggers provider verification/review.
- **Don't disable existing protections** (rate limiters, email verification) — social login plugs
  into them; pair with the `captcha` agent on the same forms where bots are a concern.

## Workflow for a typical task

1. **Detect & brief.** Read build files; find the User model, the auth controller/endpoints, the
   frontend login UI, and any existing provider code (often a half-wired Google path behind a
   flag). Identify stack + existing auth + which providers already exist. Open the project brain;
   write the operator answers + the linking decision + a tasklist.
2. **Spec the credentials for navigator.** Decide the client type(s) per surface, the exact
   redirect URIs + JS origins (dev + prod), and the env var names. Hand that spec to `navigator`
   to create the apps and harvest the IDs/secrets into `<project>/.env`. (For local-only Lane-A
   you can proceed with a real client id; full validation needs the harvested values.)
3. **Backend.** Add/repair the verifier service + the `/auth/{provider}` endpoint(s), the
   identities migration, and the resolution logic above. Reuse the app's JWT/session issuer.
   Keep the provider behind its `*_ENABLED` flag, default on for Google/Facebook, off for X.
4. **Frontend.** Add the provider buttons to the existing login/signup UI (don't build a new
   screen). Wire the GIS/FB SDK; send the token to the backend; store the returned app session
   exactly like the password path does. Localize button labels if the app is i18n'd.
5. **Validate — two lanes (see harness).** Lane A (headless verify) + Lane B (real browser via
   navigator). Assert the app issues ITS session for the correct (linked) user.
6. **Document + PDF.** Runbook + provider/redirect map (IDs, last-4) in the project brain;
   `report.py` → per-app PDF (each provider × surface ✅/⚠️/❌ + screenshots + pending + next).
7. **Improve.** Fold any new stack quirk / provider gotcha back into this SKILL.md.

## Validation harness — two lanes

**Lane A — headless / token-verify (fast, deterministic, backend-only).**
- `uv run agents/social-auth/verify_token.py` checks the backend's verifier wiring without a
  real consent dance: it asserts a **tampered/expired token is rejected** (negative path always
  runnable), and, given a real freshly-minted ID token (paste one from a real sign-in, or from
  Google's OAuth Playground), asserts the `/auth/{provider}` endpoint returns the app session and
  that a `user_oauth_identities` row now exists for the right user (find-or-link end-state).
- Assert: bad signature/`aud`/`exp` → 401; verified token for a NEW email → user created (or
  waitlisted per policy); verified token whose email matches an existing password user → **linked**
  (one user, new identity row), not duplicated.

**Lane B — real browser (proves the customer experience) — via `navigator`.**
- `navigator` drives the actual "Sign in with Google" / "Continue with Facebook" button on the
  running app (local dev URL or the deployed domain), completes the real consent with a **test
  account**, and asserts the app shows a logged-in state for that user. Screenshot every step
  (button → consent → returned/logged-in). RN/Expo native buttons aren't browser-drivable —
  validate via Lane A + an Expo dev client and **say so** in the PDF.
- These screenshots are the PDF evidence. Post-deploy, run one navigator instance per app.

## UI-clarity bar
The login screen must make the social buttons obviously safe and clear: official provider
branding, a loading state during redirect/verify (no dead clicks), a clear logged-in result, and
a human, localized message on failure (consent denied, email missing, provider down) — never a
raw error. Capture each as a screenshot for the PDF.

## Helper scripts (uv / PEP-723 — deps auto-install)
```bash
# Validate a harvested credential set + refuse a secret living in a public var:
uv run agents/social-auth/oauth_env.py check --env <project>/.env
# Lane-A token-verify harness against a running app (config-driven):
uv run agents/social-auth/verify_token.py --config <app>.social.json [--id-token <jwt>]
# Per-app PDF from results + screenshots:
uv run agents/social-auth/report.py --results results.json --shots ./shots --out <app>-social-auth.pdf
```
`verify_token.py` reads a small JSON (endpoints, provider flags, DB/HTTP end-state check) so the
same script validates any stack — see `agents/social-auth/example.social.json`.

## Self-check — you may NOT say "social login works" until all pass
- [ ] Operator gate answered & recorded (providers, linking policy, new-user/waitlist, surfaces).
- [ ] Identities table/array exists (migration applied); existing `googleId` backfilled.
- [ ] Backend verifies the token server-side (signature/`aud`/`iss`/`exp`/`nonce`); bad token → 401.
- [ ] Resolution logic correct: match-by-sub → link-by-verified-email → guarded-create; no
      auto-link on unverified/absent email; waitlist respected.
- [ ] No client/app secret in any public/front env var or tracked file (navigator GUARD-5 clean).
- [ ] Frontend buttons on the EXISTING login/signup UI; app session stored like the password path.
- [ ] **Lane A** green (link end-state asserted; negative path rejected).
- [ ] **Lane B** done (real Google + Facebook login driven by navigator; screenshots) OR
      mobile/desktop surface explicitly marked Lane-A-validated in the PDF.
- [ ] Runbook + provider/redirect map (IDs + last-4) in the project brain.
- [ ] **PDF generated** (provider × surface ✅/⚠️/❌ + evidence + pending + next) saved under the project.
- [ ] Generalizable learnings folded back into this SKILL.md.

## Gotchas (grow this list every run)
- **Google console moved (2026):** "OAuth consent screen" is now **Google Auth Platform**
  (Branding/Audience/Clients/Data Access). Old guides are stale — see navigator `auth_playbook.json`.
- **`redirect_uri_mismatch`** is the #1 Google error — exact match, register dev+prod, mind
  Spring's `/login/oauth2/code/google` default. Facebook **Strict Mode** is equally exact.
- **Client secret shows once** (Google: download the JSON; X/Facebook: copy now). navigator
  harvests in the same step; if missed, rotate — you can't re-reveal.
- **Native clients have NO secret** — Android/iOS/Chrome are public PKCE clients. A "secret" in a
  mobile/SPA bundle is a security finding; don't ship one.
- **Embedded webviews are blocked by Google** (`disallowed_useragent`) — system browser/Custom
  Tabs/`ASWebAuthenticationSession` only.
- **Facebook email can be null** even when granted (user has no confirmed email or denied it) —
  handle it; use `auth_type=rerequest` to re-ask. `public_profile`+`email` need no App Review.
- **iOS Facebook = Limited Login** (fbsdk v17+/fbsdk-next v13+): you get an OIDC JWT validated by
  nonce, **not** a Graph token — don't call `/me` on iOS; verify the JWT.
- **RN/Expo Google needs all three client IDs** (Web+Android+iOS); the **Web** client id is the
  ID-token audience on native; Android needs the SHA-1 of **each** signing key (debug + Play App
  Signing) or you get `DEVELOPER_ERROR`/code 10.
- **Google "Testing" status** caps 100 testers and expires refresh tokens in 7 days — publish to
  production for real users (manual; in MANUAL-ACTIONS).
- **Don't reuse a calendar/integration Google client for login** (tio-marco has a calendar-only
  Google service) — login is a separate concern; add a login service, keep the integration one.
- **Account-takeover trap:** never link a social identity to an existing account on an
  *unverified* email. This is the classic OAuth pre-account-hijack bug.
- **`GoogleIdTokenVerifier.verify()` can throw, not just return null (Spring/Java).** It returns
  `null` when the signature/`aud`/`iss`/`exp` checks fail, but it *throws* on a malformed credential:
  `IOException`/`GeneralSecurityException` AND unchecked `RuntimeException` — `IllegalArgumentException`
  for non-JWT input (bad base64 / non-JSON segments) and for an `alg=none` / missing-segment token.
  If you only catch the checked pair, a garbage/tampered token escapes to the generic handler as a
  **500**, which the Lane-A negative path FAILS (it demands a clean 400/401). Wrap the single
  `verify()` call in `try { … } catch (GeneralSecurityException | IOException | RuntimeException e)
  { throw unauthorized("oauth.invalidToken", …); }` and treat `null` as 401 too. Keep the try body to
  just that one call so the broad catch can't swallow an `ApiException` from your own linking code.
  (Found on "the duelo": tampered `alg=none` JWT → 500 until the catch was broadened.)
- **Flag-off must short-circuit BEFORE verification.** Check `!props.<provider>().enabled()` (and
  enabled-but-no-client-id) at the very top → return `oauth.disabled` (400) before constructing the
  verifier. This keeps the disabled endpoint cheap and deterministic, and mirrors the captcha gate's
  pass-through shape.
- **GIS button localizes via the PROVIDER, not the button (`@react-oauth/google`).** `locale` is a
  prop on `<GoogleOAuthProvider locale={i18n.language}>`, NOT on `<GoogleLogin>` — putting it on
  `<GoogleLogin>` is a TS2322 build error. The button text is chosen with `text="continue_with"` etc.

## How the user invokes this agent
Open an LLM session in the target project and point it here, e.g.:
> Read `…/agentes_perdidos/agents/social-auth/SKILL.md`. Add Google + Facebook login to this app,
> linked into the existing user/JWT system. Spec the credentials for navigator, wire backend +
> frontend, validate, and produce the PDF.
