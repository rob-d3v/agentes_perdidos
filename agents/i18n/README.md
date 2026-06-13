# i18n agent

Takes any project to full internationalization: scans front + back for user-facing strings,
extracts them into translation files with **semantic dotted keys**, authors **pt-BR + en** by
AI (always, as the source of truth), then auto-generates **~190 more languages** with a free,
keyless Google-translate script. Wires an in-app language switcher in settings and supports
cheap **incremental** re-runs.

## Use it

Open a session in any project, point the agent at [`SKILL.md`](SKILL.md), and say:

> **usa o agente do i18n — bora trabalhar nesse projeto >> `E:\path\to\project`**

- First run → full i18n.
- Later runs → "confere e atualiza o i18n" → only what changed.

## Scripts (run from the repo root with `uv`)

| Script | What | Example |
|---|---|---|
| `translate.py` | generate the ~190 non-base locales from `en`+`pt-BR` (keyless gtx, incremental, placeholder-safe) | `uv run agents/i18n/translate.py --src <locales_dir>` |
| `scan.py` | list candidate user-facing strings to key | `uv run agents/i18n/scan.py --root <ui_src>` |
| `status.py` | coverage / missing-key / orphan report | `uv run agents/i18n/status.py --src <locales_dir> --verbose` |
| `langs.json` | 192-language registry (code + native name, gtx-compatible) | add a row to add a language |

No API key required (uses Google's free `gtx` endpoint). Auto-detects `.properties`
(Java/custom-React) vs i18next `.json` from the base file and emits the same format.

## Why pt + en by AI

The two primary audiences get human-quality wording; the long tail gets machine translation —
maximum reach, minimum tokens. Translation of the 190 langs costs **zero LLM tokens** (it's a
script), per the repo's "systematic > agentic" principle.
