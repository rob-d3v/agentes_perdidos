---
name: i18n
description: >
  Internationalizes ANY project end-to-end: scans frontend AND backend for user-facing
  strings, extracts them into translation files with semantic dotted keys, authors the two
  mandatory base languages (Portuguese pt-BR + English en) by AI, then auto-generates the
  other ~190 languages with a free keyless Google-translate script (zero LLM tokens). Wires an
  easy in-app language switcher in settings (front + back), makes adding languages trivial, and
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
`scan.py` still shows real user-facing literals, you are not done. Always do the extraction
sweep, even on a project that already has some i18n (the gaps are usually in admin screens,
modals, toasts, and backend messages). Never defer extraction to a TODO and call it finished.

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
5. **Backend.** Route user-facing backend messages through the locale too (Spring
   `MessageSource` keyed by `Accept-Language`; or a backend `messages_<code>.properties`
   bundle). Internal/log-only strings can stay as-is — translate what a user actually sees.
6. **Generate the world (systematic, 0 tokens).** Run `translate.py --src <locales_dir>` to
   fill all ~190 non-base languages from en/pt-BR. Incremental by default (only missing keys);
   a local `.translate-cache.json` makes re-runs free.
7. **Report.** Run `status.py --src <locales_dir>` → write coverage to the project brain.
   Update the tasklist.
8. **Ship (always, on a separate branch).** When the work is complete and the self-check gate
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

## Self-check gate — you may NOT say "done" until all pass

Run this gate before reporting completion. If any item fails, go back to step 2/3.

- [ ] `scan.py --root <ui_src>` was run over the **whole** UI (front) **and** backend dirs, and
      every remaining hit is justified (already keyed, brand name, code/url/enum, log-only).
      Re-run it at the end: the residual list must contain **no genuine user-facing string**.
- [ ] New keys were actually **written into code** as `t(...)` calls (not just added to the
      properties/JSON). Grep a few of your new keys in the source to confirm call-sites exist.
- [ ] en + pt-BR both contain every new key with natural wording (no English left in pt-BR).
- [ ] `status.py` reports `incomplete: 0` and `missing files: 0` across all ~190 langs.
- [ ] The language switcher in settings lists the languages and actually changes + persists.
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
uv run agents/i18n/scan.py   --root <ui_src> [--ext tsx,ts,java,...]   # candidate strings
uv run agents/i18n/status.py --src  <locales_dir> [--verbose]          # coverage / gaps
```

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
