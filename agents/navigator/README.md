# navigator

Browser-driving GUI agent. Does the **web-dashboard work** other agents can't — because
Claude-in-Chrome refuses financial surfaces (`dashboard.stripe.com`, `checkout.stripe.com`). It
auto-routes a 4-tier browser backend, clicks through dashboards, completes hosted-checkout card
entry, and **harvests credentials/IDs into the target project's gitignored `.env`** — never here.

Pairs with the **stripe** agent: navigator = hands/eyes (GUI + harvest + env); stripe = brain
(code + two-lane validation + PDF).

## Quickstart
1. **Bring up a backend.** Start a warm Chrome and register `chrome-devtools-mcp` (Tier 2):
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
     --remote-debugging-port=9222 --user-data-dir="$env:USERPROFILE\.chrome-navigator"
   ```
   Add to the `mcpServers` map in `~/.claude.json`:
   ```jsonc
   "chrome-devtools": { "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest", "--browserUrl", "http://127.0.0.1:9222"] }
   ```
   Restart the session.
2. **Log into Stripe** in that Chrome window (handles 2FA; navigator reuses the session).
3. **Check backends:** `uv run agents/navigator/backend_check.py --surface stripe-dashboard`
4. **Point an LLM at `SKILL.md`** inside the target project and give it the task.

## Helpers (all `uv run`, no setup)
| Script | Does |
|---|---|
| `backend_check.py` | Probe the 4 backend tiers, recommend one per `--surface`. No browser driving. |
| `playbook_run.py` | Print the ordered Stripe-dashboard checklist for a surface + mode. |
| `secrets_writer.py` | **Safely** write harvested keys into the target `.env`: refuses agentes_perdidos paths, verifies gitignore, idempotent upsert, `--allow-live` gate for live keys. |
| `stripe_playbook.json` | Declarative URL/step/scope data the playbook runner reads. |

## Safety
- Secrets only ever land in the **target project's** gitignored `.env` (or its deploy panel).
- Live actions need the operator live-promotion gate **and** `--allow-live`.
- Keys appear in docs as name + last-4 only. navigator never runs a real charge.

See [`SKILL.md`](SKILL.md) for the full decision matrix, playbooks, and security model.
