---
name: i18n
description: >
  Internationalizes ANY project end-to-end: scans frontend AND backend for user-facing
  strings, extracts them into translation files with semantic dotted keys, authors the two
  mandatory base languages (Portuguese pt-BR + English en) by AI, then auto-generates the
  other ~190 languages with a free keyless Google-translate script (zero LLM tokens). Wires an
  easy language switcher into settings AND every pre-auth surface (landing / login / signup) so
  foreign visitors aren't stranded before login (front + back). Guarantees completeness with a
  code↔base audit (no key ever renders as raw text on screen), makes adding languages trivial, and
  supports incremental re-runs that pick up ONLY what changed. Adapts to the project's native
  format (i18next JSON for React/React-Native, .properties for Java/Spring/custom-React). Use
  when asked to "internationalize / i18n / translate this project", "add languages", or "check
  and update the i18n". Launches sub-agents for big projects.
---

# i18n agent

You take a project from "hardcoded strings" to "fully internationalized, ~200 languages, user
can switch language in settings". Two languages are **always** authored by you with real
quality — **pt-BR (Portuguese)** and **en (English)** — and are the source of truth. Every
other language is generated mechanically by `translate.py`. The user maintains the exotic
languages; you guarantee pt + en are perfect and the machinery scales to ~200.

> Invocation the user will use: **"usa o agente do i18n — bora trabalhar nesse projeto >> `<PATH>`"**.
> First run on a project = full i18n. Later runs = "confere e atualiza o i18n" = incremental.

## Operating rules (read AGENTS.md "Lost-agent operating rules" first)

- The **target project is your workspace**. Persist your tasklist, key-map, decisions and
  coverage reports in the *target project's own brain*: use an existing `llm-wiki`/`.llm-wiki/`
  /wiki dir if present, else create `./.i18n/` at the project root (`tasklist.md`, `keymap.md`,
  `progress.md`, `coverage.json`). Do **not** write project state into `agentes_perdidos`.
- Generalizable learnings (a new stack adapter, a better heuristic, a gotcha) go back into
  **this** `SKILL.md` — that is your self-improvement loop. Project-specific facts stay in the
  project brain.
- Never overwrite the base languages with machine output. `en` + `pt-BR` are sacred.
- The other ~190 files carry a header marking them machine-generated — they are safe to
  regenerate any time.

## Decision logic — stack → format adapter

Detect the stack from build files, then pick the **framework-native** format (locked decision):

| Stack (detect by) | Runtime format | Source-of-truth files | Switch mechanism |
|---|---|---|---|
| **i18next** (`i18next` in package.json; React / React-Native / Expo) | per-locale JSON `locales/<code>.json` (or `src/i18n/<code>.json`) | `en.json`, `pt-BR.json` | `i18n.changeLanguage(code)` + persist (AsyncStorage / localStorage) + `fallbackLng:'en'` |
| **Custom React** (theAPIAniaAPP: own `I18nContext`, `t('a.b', 'default')`) | `messages_<code>.properties` in `public/locales/` | `messages_en`, `messages_pt-BR` | existing context + `localStorage` |
| **Java / Spring** | `messages_<code>.properties` (`ResourceBundle`) under `resources/` (or `i18n/`) | `messages_en`, `messages_pt-BR` | `Accept-Language` → `LocaleResolver`/`MessageSource`; or InterPRO `Tools.translate()` pattern + restart |
| **Vue / Svelte / other** | framework idiom (`vue-i18n` JSON), else `.properties` | en + pt-BR | framework switch API |

**Keys are always semantic dotted** — `settings.audio.title`, `library.error.downloadFailed`,
`avatars.filter.topRated`. Group by screen/feature. Reuse common keys (`common.cancel`,
`common.save`). This matches theAPIAniaAPP's existing 466-key scheme and diffs cleanly for
incremental runs.

## Definition of done (read this first)

Internationalizing a project is **not** just syncing locale files. The core job is
**extraction**: every user-facing hardcoded string becomes `key + value`, the code calls
`t('key')`, the base files (en + pt-BR) get the wording, and the ~190 langs get generated.
A run that only backfills existing keys across languages (locale-sync) is **incomplete** — if
`scan.py` still shows real user-facing literals, **or `audit.py` shows a key the code uses but
base lacks (or a label rendered without `t()`)**, you are not done. Always do the extraction
sweep, even on a project that already has some i18n (the gaps are usually in admin screens,
modals, toasts, and backend messages). Never defer extraction to a TODO and call it finished.
The completeness invariant below is non-negotiable: a key visible on screen as raw text
(`nav.whatsapp`) is the single worst i18n failure and the gate exists to make it impossible.

## Workflow for a typical task

1. **Detect & brief.** Read build files; find the i18n lib + locale dir (or decide where it
   goes). Open/create the project brain. Write a tasklist + the stack/format decision.
2. **Inventory (systematic).** Run `scan.py --root <ui_src>` to list candidate user-facing
   literals per file (frontend components, dialogs, toasts, menus; and backend user-facing
   messages/exceptions). It is a heuristic feeder — you decide which are real.
3. **Extract (agentic).** For each real string: assign a semantic key, replace the literal in
   code with the framework call (`t('key')`, `{t('key')}`, `Tools.translate("key")`, etc.),
   and add the key to the **en** and **pt-BR** base files with natural wording in each.
   Preserve interpolation: keep `{{var}}`/`{var}`/`%s` in the value; don't translate variable
   names. Record every key in `keymap.md`.
4. **Switcher + plumbing.** Ensure i18n is initialized at app entry, locale is detected on
   first run with a sane fallback (`en`), persisted, and re-applied on launch. Build/repair the
   **language selector in the settings UI**: list languages from `langs.json` (code + native
   name), on select → change language + persist. Make adding a language a one-file change.
   **Pre-auth surfaces are mandatory (see below).** A switcher buried in post-login settings
   strands every foreign visitor who can't read the landing/login page in the first place.
5. **Backend.** Route user-facing backend messages through the locale too (Spring
   `MessageSource` keyed by `Accept-Language`; or a backend `messages_<code>.properties`
   bundle). Internal/log-only strings can stay as-is — translate what a user actually sees.
6. **Reconcile code ↔ base (the completeness gate).** Run
   `audit.py --root <ui_src> --src <base_dir> --strict --check-empty`. This catches the failure
   the other scripts can't: a key referenced in code (`t('nav.whatsapp')`) but **missing from
   en/pt-BR** — which makes i18next render the raw key on screen. Fix every `USED_BUT_MISSING`
   (add the key to en+pt-BR), triage every `RENDER_BARE` (a label var rendered without `t()`)
   and `PHANTOM` (key-like literal in a real namespace). Re-run until clean. See "Completeness
   invariant" below. Do this **before** generating the world — no point translating a key the
   code can't even reach, and no point shipping one the code references but base lacks.
7. **Generate the world (systematic, 0 tokens).** Run `translate.py --src <locales_dir>` to
   fill all ~190 non-base languages from en/pt-BR. Incremental by default (only missing keys);
   a local `.translate-cache.json` makes re-runs free.
8. **Report.** Run `status.py --src <locales_dir>` → write coverage to the project brain.
   Update the tasklist.
9. **Ship (always, on a separate branch).** When the work is complete and the self-check gate
   passes, commit everything and push to a **dedicated branch — never `main`/`master`**:
   ```bash
   git checkout -b i18n/internationalization     # or i18n/update-<date> on a re-run
   git add -A
   git commit -m "i18n: extract UI strings + generate ~190 locales"
   git push -u origin i18n/internationalization
   ```
   - Branch off the current branch; if the repo has no commits/remote, say so instead of
     forcing. Use a fresh branch name per run (e.g. `i18n/update-2026-06-13`) so re-runs don't
     collide. Report the branch + a one-line diffstat. Open a PR only if the user asks.
   - Generated locale files are large; that's expected — they belong in the commit.

## Pre-auth language switcher — mandatory on landing & login

A user who lands on a **public page in a language they don't read leaves before they ever reach
settings**. So the switcher must live on every surface a visitor hits *before* authenticating —
not only in the post-login app. Treat this as part of "done", not a nice-to-have.

Rule: **if the project has a landing page and/or a login/signup page that are separate from the
authenticated app, each of those pages MUST expose the language switcher.** Detect these surfaces
explicitly during step 1 (look for `landing/`, `Landing*`, marketing/home routes, `login`,
`signin`, `signup`, `register`, `auth/` pages, a public root route `/`).

- Place it where a first-time visitor sees it without scrolling/hunting: header/navbar corner,
  or a compact flag/globe dropdown top-right (footer is a weak fallback, header preferred).
- Use the **same** language list + change/persist logic as the settings switcher — extract one
  shared `<LanguageSwitcher>` component (or shared hook) and drop it into landing, login, AND
  settings. Don't fork three copies.
- It must work **before any session exists**: locale is stored in `localStorage`/cookie (not
  tied to a user record), applied on load, and survives the navigation into login → app.
- The whole landing + login + signup copy must itself be keyed (`t(...)`), not hardcoded —
  these are the highest-value strings to translate and are often missed because they live
  outside the authed app's component tree.
- Backend-rendered auth pages (Spring/Thymeleaf login) honor `Accept-Language` and expose the
  switcher too (a `?lang=` link or form that sets the locale cookie).

If a project is single-surface (no separate landing/login — e.g. switcher already in a top bar
shown on every route), one well-placed switcher satisfies this. The test is reachability: **can
a visitor who can't read the default language change it from the very first screen?**

## Completeness invariant — the InterPRO rule (the crown jewel)

The user's old tool *never wrote an incomplete locale*: for each file it reconciled three ways —
remove orphans, fill every key missing from base, reject empty values — and refused to finish
until all three held. Port that invariant. **You may not finish while ANY of these is true:**

1. **A key used in code is absent from base.** `t('k')`/`i18nKey="k"`/`Tools.translate("k")`
   referencing a key that en/pt-BR don't define → i18next shows the literal `k` on screen (the
   `nav.whatsapp` sidebar bug). Caught by `audit.py` → `USED_BUT_MISSING` (hard error).
2. **A locale is missing a base key, or a base value is empty.** Caught by `status.py`
   (`incomplete`, `missing files`, `empty base values`) and `audit.py --check-empty`.
3. **A label that holds a key is rendered without `t()`.** The #1 silent leak — see the
   data-driven-label gotcha below. Caught by `audit.py` → `RENDER_BARE` (triage each).

`audit.py` is **i18next-plural-aware**: a `t('k', {count})` call resolves to `k_one`/`k_other`,
so a bare `k` used in code counts as present when base holds any plural variant — don't add a
redundant bare `k` to satisfy the gate. It is the gate that closes the loop the older scripts
left open (`scan.py` only sees *unwrapped* literals; `status.py` only compares locales to each
other). It reports:
`USED_BUT_MISSING` (error, fails `--strict`), `RENDER_BARE` + `PHANTOM` (warn — precise review
lists; triage, fix the real ones), `UNUSED_IN_CODE` (warn — orphans, never auto-deleted). For
pure-i18next projects the off-the-shelf equivalent is `i18next-cli extract --ci` / i18nGuard; the
stack-agnostic `audit.py` is preferred here because it also handles Spring `.properties`.

```bash
uv run agents/i18n/audit.py --root <ui_src> --src <base_dir> --strict --check-empty
# extra helper names (Spring / custom), or custom label fields:
uv run agents/i18n/audit.py --root src --src i18n --call t,translate,Tools.translate,getMessage \
      --label-fields label,title,heading,tab
```

## Runtime safety net — make a missing key loud, never silent

Belt-and-suspenders so a key that slips past the gate degrades gracefully instead of showing raw:
- **i18next**: set `fallbackLng: 'en'` (worst case is English, never the raw key) and wire
  `saveMissing: true` + a `missingKeyHandler` that `console.error`s in dev (or `parseMissingKeyHandler`
  returning a loud marker). This surfaces drift the moment a dev hits the screen.
- **Spring**: configure `MessageSource.setUseCodeAsDefaultMessage(false)` so a missing code throws
  `NoSuchMessageException` (loud) instead of silently echoing the code into the UI.

## Self-check gate — you may NOT say "done" until all pass

Run this gate before reporting completion. If any item fails, go back to step 2/3.

- [ ] `scan.py --root <ui_src>` was run over the **whole** UI (front) **and** backend dirs, and
      every remaining hit is justified (already keyed, brand name, code/url/enum, log-only).
      Re-run it at the end: the residual list must contain **no genuine user-facing string**.
- [ ] **`audit.py --root <ui> --src <base> --strict --check-empty` passes**: `USED_BUT_MISSING`
      = 0 (no key referenced in code is missing from base), `RENDER_BARE` and `PHANTOM` triaged
      (each is either fixed or confirmed a false positive — e.g. a `helpKey=` id), empty base
      values = 0. This REPLACES the old "grep a few new keys" spot-check — it is exhaustive.
- [ ] en + pt-BR both contain every new key with natural wording (no English left in pt-BR).
- [ ] The project's **real build passes** (`npm run build` / `tsc -b`, the same command CI/Docker
      runs) — not just `tsc --noEmit`. Catches `t`-var collisions + prop-rename mismatches.
- [ ] `status.py` reports `incomplete: 0`, `missing files: 0`, **and `empty base values: 0`**
      across all ~190 langs.
- [ ] The language switcher in settings lists the languages and actually changes + persists.
- [ ] **Pre-auth switcher present**: every separate landing page and login/signup page exposes
      the switcher (shared component), it works with no session, and landing+login+signup copy
      is fully keyed. (Single-surface app with an always-visible switcher passes trivially.)
- [ ] Coverage + key count written to the project brain; tasklist updated.
- [ ] All changes committed and pushed to a **dedicated branch** (not `main`), branch name
      reported. (Open a PR only if asked.)

If the project already had partial i18n, the gate still applies — "it was mostly done already"
is not a pass. Extract the remaining gaps (admin, modals, toasts, backend) before finishing.

## Incremental / "confere e atualiza" mode

When re-run on an already-i18n'd project:
- `status.py --src <dir> --verbose` → what's missing per language, orphan keys (keys deleted
  from base but lingering in targets), and the distinct keys needing translation.
- `scan.py` again over changed areas → find NEW hardcoded strings added since last time
  (cross-check against `keymap.md` / existing base keys; ignore anything already keyed).
- Key only the new strings into en + pt-BR, then `translate.py` (only-missing) backfills the
  ~190. Prune orphans if the user wants. Cheap and idempotent.

## Sub-agents (for big projects)

Fan out when a project has many UI areas: spawn one Explore/extract sub-agent per area
(`admin/`, `pages/`, `controllers/`, `settings/`…), each returning a `{file, line, text,
suggestedKey}` list. Merge their key-maps, dedupe keys, then YOU do the base-language wording
in one pass for consistency. Keep translation (the ~190 langs) on the script, never on
sub-agents — that's the token-saving boundary.

When sub-agents replace literals in code, have each return a JSON keymap
`[{key, en, ptBR}]` and write it to a file (or return it) — then merge ALL keymaps into the
base `en`/`pt-BR` centrally with `merge_keys.py` (below). Never let sub-agents edit the base
files in parallel (write conflicts + inconsistent wording). Sub-agents edit only *code* files
(disjoint per area) + add the import (`from <i18n_pkg> import translate` / `import ...Tools;`).

## Merging extracted keys — `merge_keys.py`

After an extraction pass, append the new keys to the base files (idempotent — existing keys
are never overwritten, base languages stay hand-authored):

```bash
uv run agents/i18n/merge_keys.py --src <languages_dir> --keys a.json b.json ...
# i18next JSON base (en.json/pt-BR.json) — auto-detected, or force it:
uv run agents/i18n/merge_keys.py --src <dir> --format json --keys a.json b.json ...
```

Each `*.json` is a `[{key, en, ptBR}]` list (or an object with a `keymap` list). It dedupes
across files (first wins — `common.*` repeated by several sub-agents collapses) and writes UTF-8.
Auto-detects the base format from the dir: **properties** (`messages_en.properties`, flat keys,
real newlines → literal `\n`, leading spaces escaped) or **json** (`en.json`/`pt-BR.json`, i18next —
dotted keymap keys are *nested* into the tree, same flatten/unflatten model `translate.py` uses;
it errors on a leaf/parent key collision so you rename rather than corrupt). Then run `translate.py`
to backfill the ~190 langs for the newly added keys (incremental — only the new keys hit the net).

## Gotcha — data-driven label/route tables are the #1 raw-key leak

The most common way a key ends up showing raw on screen is **not** a missing base entry — it's a
config array whose render forgot `t()`:

```tsx
const nav = [{ to: "/wa", label: "nav.whatsapp" }, ...];   // label IS an i18n key
nav.map(({ label }) => <li>{label}</li>)                   // BUG: renders the key literally
nav.map(({ label }) => <li>{t(label)}</li>)                // correct
```

Both halves hide from the usual checks: `scan.py` skips it (it's not a bare English literal),
and `status.py` is blind to code. The same trap lurks in `columns`, `tabs`, `menu`, `steps`,
`options` config arrays. **Rule:** when a data field holds a key, its render MUST wrap it in
`t(field)`, and the key MUST exist in base. `audit.py`'s `RENDER_BARE` check catches exactly this
(a label-ish var rendered without `t()` in a file that assigns key-like literals to labels) — and
its `PHANTOM`/`USED_BUT_MISSING` checks catch the missing-key half. When you build such a table,
prefer keying it so the render is unconditionally `t(item.label)`.

## Gotcha — `const { t } = useTranslation()` collides with existing `t` vars

The react-i18next hook conventionally binds `t`. Many files already use `t` for something else —
theme-token snapshots (`const t = tokensRef.current; t.accent`), time/date vars, generic temps.
Dropping `const { t } = useTranslation()` into such a file causes **TS2451 "cannot redeclare
block-scoped variable 't'"** and every old `t.foo` access then resolves against the `TFunction`
(TS2339 "Property 'foo' does not exist"). The build (`tsc -b`) catches it; `tsc --noEmit` may not.
Before adding the hook, grep the file for a bare `t` binding and rename the **pre-existing** one
(e.g. tokens → `tk`) — never rename the i18n `t`, since `t('key')` call-sites are everywhere.
Same trap for any short alias the framework injects (`i18n`, `t`).

## Gotcha — verify with the project's REAL build, not just `tsc --noEmit`

The done-gate compile check must run the project's actual build script (`npm run build` →
often `tsc -b && vite build`), not a loose `tsc --noEmit`. `tsc -b` (build mode, project refs)
is stricter and catches prop-rename mismatches and the `t`-collision above that `--noEmit` slides
past. A green `--noEmit` that later fails the CI/VPS Docker build (`RUN npm run build` exit 2) is
the classic miss. Run the same command the deploy runs. Watch for **prop renames during keying**:
if you rename a prop while threading `t` (e.g. `seedPrompts` → `seedPromptKeys` because the child
now calls `t()` itself), update every call-site — a child that takes *keys* must be passed raw
keys, not pre-translated strings.

## Gotcha — ~190 locale chunks OOM the production Docker build

Lazy-loading the world (`import.meta.glob('./locales/*.json')`, ~190 JSON) adds ~190 rollup
chunks. That spikes vite/rollup **peak heap during "rendering chunks"**. It builds fine locally
(node 22/24 default heap is large) but the deploy image often pins **node 20-alpine** (~2GB
default heap) and dies mid-build with `FATAL ERROR: Reached heap limit Allocation failed -
JavaScript heap out of memory` → `npm run build` exit **1** (note: exit 1 = vite/rollup stage,
exit 2 = tsc stage — use the code to tell which half failed). A clean local build that fails CI/VPS
is the tell. Fixes, in order:
- In the build Dockerfile stage set `ENV NODE_OPTIONS=--max-old-space-size=4096` before
  `RUN npm run build`. Cheapest, durable. (Match the project's other build-mem flags if any.)
- Reproduce the deploy env to confirm — `docker build --target build -t x .` against the
  frontend Dockerfile reproduces the exact node-20 OOM; rebuild after the flag to verify.
- If it still OOMs, lower peak: `manualChunks` to group the locales, or don't eager-import the
  base locales twice (a static `import en from './locales/en.json'` plus a glob that also matches
  `en.json` triggers vite's "dynamically and statically imported" warning and double-counts).
This is now part of "verify with the real build" — run/inspect the **containerized** build for
any project that ships ~190 locale files, not just the host `npm run build`.

## Gotcha — custom `.properties` loaders may not unescape `\n`

Java's `java.util.Properties.load` unescapes `\n \t \r \uXXXX` for free, so multi-line values
stored as `...line1\nline2...` render correctly. But a hand-rolled loader (common on the Python
/ custom-React side) often unescapes only `\uXXXX` and leaves `\n` literal — every multi-line
dialog then shows a literal backslash-n. Before authoring multi-line base values, check the
project's loader (`get_text`/`getString` path); if it doesn't decode `\n`, fix it with a
single-pass decoder (`\uXXXX` + `\n \t \r \\`) so it matches the Java side. Single-pass matters
so an escaped backslash `\\` isn't double-processed.

## Gotcha — gtx placeholder masking covers precision formats

`translate.py`'s `PLACEHOLDER_RE` masks `%s %d %1$s %.2f %+.3f %05d` and `{var} {{var}} {0}`.
If a project uses an exotic format token, add it to the regex or gtx may corrupt it.

## The translation skill — `translate.py`

Keyless, dependency-free, uses Google's free `gtx` endpoint (decoded from InterPRO's
`TranslationService.java`). Masks placeholders before sending and restores them after; if a
placeholder is lost in translation it keeps the source string instead of corrupting it.

```bash
# Fill all langs (incremental) — auto-detects properties vs json from the base file:
uv run agents/i18n/translate.py --src <locales_dir>

# Subset / dry-run / force-all / no-cache:
uv run agents/i18n/translate.py --src <dir> --langs es,fr-FR,de,ja,ar --dry-run
uv run agents/i18n/translate.py --src <dir> --all --no-cache
```

- `--base en,pt-BR` (default): never translated; first listed is the preferred gtx source.
- Skips keys that already have a value in a target (so it only does new work).
- `langs.json` (192 codes + native names, gtx-compatible) is the registry; subset with
  `--langs`. Add a language = add a row there (or it's already covered).
- Quality caveat: gtx is machine translation — great for reach, not nuance. en/pt-BR are
  AI-authored precisely because the two primary audiences deserve real quality.

## Helper scripts

```bash
uv run agents/i18n/scan.py   --root <ui_src> [--ext tsx,ts,java,...]   # candidate UNWRAPPED literals
uv run agents/i18n/audit.py  --root <ui_src> --src <base_dir> --strict --check-empty  # code↔base gate
uv run agents/i18n/status.py --src  <locales_dir> [--verbose]          # cross-language coverage / gaps
```

The three are complementary and together close every completeness hole: `scan.py` finds strings
**not yet keyed**; `audit.py` finds keys **used in code but missing/unwrapped in base** (and empty
base values); `status.py` finds keys **missing across the ~190 locales**. Run all three before "done".

## Gotchas

- gtx is unofficial + rate-limited → `translate.py` batches with a thread pool + exponential
  backoff; lower `--workers` if you hit 429s.
- Protect interpolation tokens and HTML — already handled by the masker, but keep variable
  syntax consistent in your base strings (prefer one style per project).
- Right-to-left languages (ar, fa, he, ur…) need the UI to honor `dir="rtl"`; flag it, set it
  from the active locale where the framework supports it.
- hey-ania builds only from an ASCII path (`E:\heyania-build`, not the accented repo path) —
  irrelevant to i18n file edits, but relevant if you try to run a native build to verify.
- Don't translate enum values, API keys, route names, or log-only strings — only what a user
  reads on screen.
- Windows consoles default to cp1252 → printing UI strings (arrows, accents, emoji) can raise
  `UnicodeEncodeError`. The scripts force UTF-8 stdout; if you print scan output yourself, do
  the same or pipe `--json` to a file with an explicit `C:/.../Temp/...` path (MSYS `/tmp` and
  Windows Python resolve `/tmp` differently).
- The extraction sweep scales with sub-agents: one worker per directory, each editing only its
  own (disjoint) files and **returning** the `{key, en, pt}` list rather than editing the
  shared base files — then the main agent merges all keys into en + pt-BR centrally to avoid
  write races. Run `translate.py` once after the merge.
