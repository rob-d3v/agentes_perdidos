# agentes_perdidos

A public collection of **AI agents** built to handle real tasks I (and anyone with repo
access) keep needing. Each agent is a self-contained folder with a `SKILL.md` (the brain —
what it does and how it decides) plus any code it needs to run.

You drive an agent by opening an LLM coding session (Claude Code, Codex, OpenCode, etc.)
**in any project**, pointing it at an agent's `SKILL.md`, and giving it a task. The agent
reads its instructions and executes.

> Anyone with access can use these, no problem. All the rules and markdown for each agent
> live in its folder.

## Agents

| Agent | What it does | Folder |
|---|---|---|
| **image-creator** | Generates missing/fallback image & video assets across 3 APIs with auto-fallback: transparent images → OpenAI `gpt-image-1.5`, normal/photographic → Gemini "Nano Banana", video → Kling AI. Reads a project's `prompts.md`, drops files at the right paths, tracks estimated spend. | [`agents/image-creator/`](agents/image-creator/) |
| **bucket** | Offloads a project's static, browser-served assets (images, gifs, video, fonts) to object storage — Cloudflare R2 (hot/CDN) and/or Backblaze B2 (large/archival) — then rewrites the code to public bucket URLs. Cuts VPS bandwidth, speeds page loads. Scans, routes by purpose, uploads, verifies, swaps paths (reversible). | [`agents/bucket/`](agents/bucket/) |
| **cloudflare** | Drives the owner's whole Cloudflare account via the account REST API + R2 S3 keys: R2 buckets/CORS/presign/lifecycle/public-URLs, DNS records, cache purge, Workers + Pages deploys (wrangler), Turnstile widget creation, Email Routing. Ships a read-safe `cf.py` that verifies the (account-owned) token, maps the fleet, and edits CORS with a mandatory GET-first-then-merge guardrail. Never prints secret values; never blind-PUTs a CORS ruleset. | [`agents/cloudflare/`](agents/cloudflare/) |
| **design-reviewer** | Senior product-designer agent. Diagnoses what looks amateurish in a UI and produces a professional, buildable redesign/refactor plan (layout, hierarchy, color, motion, window chrome, branding/mascot) that preserves all functionality, plus an AI-asset spec routed to image-creator. Audits which assets are actually used. | [`agents/design-reviewer/`](agents/design-reviewer/) |
| **lost-finder** | Forensic hunter for lost files. Finds files you can describe but can't locate — even renamed, moved to a backup, or in the Recycle Bin — by matching on **content**: images by color signature ("yellow logo on blue background") with optional Gemini vision-verify, PDFs by extracted-text keywords, both ranked + copied into one folder to eyeball. Plus a **local-only secrets mode** to recover your *own* lost wallet creds: BIP39 checksum-validated seed detection, MetaMask vault-blob extraction, optional local OCR. | [`agents/lost-finder/`](agents/lost-finder/) |
| **second-brain** | Builds & maintains a persistent **LLM-wiki** "second brain" for any project (Karpathy "LLM Wiki" pattern, productized). Compiles knowledge once into an interlinked markdown wiki that lives **inside the project's Obsidian vault** and keeps it current — `onboard`, `ingest`, `query`, `lint`. Generic non-confidential knowledge is shared once here and linked, never duplicated per project; confidential brains stay in-project. | [`agents/second-brain/`](agents/second-brain/) |
| **remodeling** | Remodels an app so it reflects the **real, verifiable identity** of its true owner instead of fake/sample persona content. Deep-researches the real person with geo-anchored sub-agent searches (beats homonyms; drives official registries via a browser when needed), rewrites all persona copy keeping only sourced facts and turning the unverified into `@em_breve` placeholders (**hard anti-fake rule**), and **face-swaps** the images that show the person to their real face (via image-creator) while preserving pose/clothes/lighting. Publishes assets via the bucket agent and records a sourced dossier in the target project's brain. Changes content, never layout. | [`agents/remodeling/`](agents/remodeling/) |
| **stripe** | Implements **and validates** a Stripe integration end-to-end using **homologation (TEST-mode) keys**, so a client's business is provably ready to sell. Detects the stack (Spring Boot / React-Vite / RN-Expo) and surface (Checkout / Payment Element / Subscriptions + Portal / Connect), provisions the Stripe account if missing, stands up a **test environment separate from prod** (test keys, a mirrored test catalog, Stripe-CLI webhook forwarding), then runs a **two-lane validation harness** — headless API (test PM tokens, `stripe trigger`, Test Clocks) + real **browser** checkout (test-card matrix, screenshots) — asserting app/DB end-state, webhook signature & idempotency, and a clear customer UI. Documents it in the project's LLM-wiki and emits a per-app **PDF** of functional vs pending. | [`agents/stripe/`](agents/stripe/) |
| **ai-visibility** | Makes a project's content **citable by AI answer engines** (ChatGPT, Claude, Perplexity, Gemini, Google AI Overviews) — GEO/AEO, not classic SEO. Audits any page (blog / SPA landing / product) against a 23-element framework, scores it 0-100 (`score.py` fetches as an AI crawler — **no JS execution**), and emits a content-type-aware, prioritized action plan. Auto-applies the safe wins (JSON-LD schema, last-updated, tables, meta, Q&A headings). **Element 0 = extractability**: knows a JS-only SPA is invisible to AI crawlers and gates everything on prerender/SSR before any content polish. | [`agents/ai-visibility/`](agents/ai-visibility/) |
| **navigator** | Browser-driving GUI agent that does the dashboard work other agents can't (Claude-in-Chrome refuses Stripe surfaces). Auto-routes a 4-tier browser backend ladder (Claude-in-Chrome → `chrome-devtools-mcp` Puppeteer → hermes stealth/Camofox → computer-use), logs into web dashboards, **creates** Stripe accounts/products/keys/webhooks/portal or **harvests** from existing ones, completes hosted-checkout card entry, and writes the credentials/IDs into the **target project's gitignored `.env`** (never here). Handles TEST and gated LIVE. Pairs with **stripe** (navigator = GUI + harvest + env; stripe = code + validation + PDF). | [`agents/navigator/`](agents/navigator/) |
| **social-auth** | Implements **and validates** "Sign in with Google / Facebook" wired into a project's **existing** user system (X adapter present but flag-off — its free tier ended). Detects the stack (Spring Boot / FastAPI / React-Vite / Next / RN-Expo / JavaFX), adds a server-side token **verifier**, a correct **account-linking** model (`user_oauth_identities`, link only on provider-verified email — no account-takeover), and the provider buttons on the existing login UI; validates two ways (headless token-verify + real browser login via **navigator**) and emits a per-app **PDF**. Hands credential creation/harvest to **navigator**. | [`agents/social-auth/`](agents/social-auth/) |
| **captcha** | Implements **and validates** bot-protection on auth/abuse-prone forms. Default **Google reCAPTCHA** (v3 score + v2 fallback); **Cloudflare Turnstile** as a drop-in alt. Renders the widget with the public site key and adds the **mandatory server-side `siteverify`** that **fails closed** and runs *before* the form action — the #1 real captcha bug is a widget that's never verified. Validates deterministically with the providers' **test keys** (pass/block/replay) + a real browser pass; per-app **PDF**. Hands key creation to **navigator**. | [`agents/captcha/`](agents/captcha/) |
| **i18n** | Internationalizes any project end-to-end (front + back). Extracts hardcoded strings into translation files with semantic dotted keys, authors **pt-BR + en** by AI (always, source of truth), then auto-generates **~190 more languages** with a free keyless Google-translate script (0 LLM tokens). Wires an in-app language switcher in settings, adapts to the project's native format (i18next JSON / Java `.properties`), and supports cheap incremental re-runs. | [`agents/i18n/`](agents/i18n/) |
| **security-reviewer** | Two-layer application-security review for any repo. Layer 1 = a deterministic, un-injectable CLI gate (Semgrep + Gitleaks → SARIF) plus opt-in language-native SAST, a dependency / supply-chain pass (pip-audit/osv-scanner/Trivy/Dependency-Check), and a **built-artifact** secret scan (catches `VITE_`/`NEXT_PUBLIC_`/`EXPO_PUBLIC_` keys inlined into the shipped bundle). Layer 2 = an AI reasoning core (Anthropic's MIT `claude-code-security-review` prompt: 3-phase, ≥0.8 confidence, 18-item exclusion list) that traces dataflow to find the logic bugs SAST misses. Ships per-stack OWASP Top-10 checklists. **Read-only on source** (reports to a gitignored dir); fixes are PR-only; per-repo findings stay in the target's own brain. | [`agents/security-reviewer/`](agents/security-reviewer/) |
| **architecture-auditor** | Senior-engineer **read-only** architecture diagnosis. Reverse-engineers a codebase into Clean-Architecture layers, asserts the Dependency Rule, scores modules on SOLID + coupling/cohesion + DDD bounded contexts, computes hard metrics (cyclomatic/cognitive complexity, Ca/Ce/Instability, duplication, dependency cycles via lizard/radon/jscpd/dependency-cruiser), and emits a prioritized, phased refactoring roadmap (Strangler Fig / Branch-by-Abstraction) ranked by blast-radius × severity. Proposes, never edits — hands the roadmap to **clean-refactorer**. | [`agents/architecture-auditor/`](agents/architecture-auditor/) |
| **performance-engineer** | Measure-first performance agent: profiles to find the single real hotspot per ecosystem (React DevTools / Node clinic+0x / Python cProfile+py-spy+scalene / JVM async-profiler+JFR+MAT), applies the one highest-self-time fix, then **re-profiles to prove the win AND asserts byte-identical output** (behavior preserved). Never speculative optimization. Each fix is an isolated revertible commit; ships a `behavior_diff.py` equivalence oracle. | [`agents/performance-engineer/`](agents/performance-engineer/) |
| **clean-refactorer** | Executes **behavior-preserving** structural refactors behind a safety net. If the target is untested it first generates + commits characterization (golden-master) tests, then separates concerns into domain/application/infrastructure/interfaces via Branch-by-Abstraction / Strangler Fig — each move a tiny revertible commit, re-running the test net after every step (revert on red) — and locks the new boundaries with CI fitness functions (dependency-cruiser / ArchUnit). Consumes architecture-auditor's roadmap. | [`agents/clean-refactorer/`](agents/clean-refactorer/) |
| **guardian** | VPS backup + disaster-recovery daemon. Auto-discovers every meaningful docker volume on a host (app data + PaaS control-plane), tars each, keeps one local copy, and pushes to a private Backblaze B2 bucket with rolling 3-daily + 3-weekly retention per volume; reports to WhatsApp. A companion restore tool rebuilds all volumes on a fresh machine from B2. | [`agents/guardian/`](agents/guardian/) |
| **habitar** | The anti-ghost-town agent. Makes a launched-but-empty product look **and be** inhabited — **without fabricating social proof**. One rule, in its frontmatter so it can't drift: *never creates a person, an opinion, or a number that did not happen* — it refuses fake users/reviews/votes/purchases and inflated counters, and answers every such request with the nearest legitimate substitute. Crawls every public surface as an anonymous visitor, scores each one on a 5-dimension **liveness ledger** (Population/Variety/Activity/Continuity/Invitation) under an **honesty multiplier** that makes a surface which looks alive *because it lies* score below an honestly empty one; leak-scans every JSON response for PII and secrets; and lints every on-screen number for substantiation and every outbound `sameAs`/social claim for actually existing. Then `surface` (dedupe, light up dark features, use static-safe content already shipped), `invite` (empty state → first action, **true** scarcity), `return` (digest/feed/notify-me), `supply` (disclosed first-party catalog). **Gated on measurement** — no analytics, no claimed win — and it refuses to rank storefront work above distribution below a traffic floor, because polishing a shop nobody walks past is worth ~0. `--portfolio` ranks N apps and names the ones to let die. Seam with **ai-visibility**: *that* agent asks whether the crawler can read it; this one asks whether there's anything there to read. | [`agents/habitar/`](agents/habitar/) |
| **branch-consolidator** | The "MAIN" agent. Consolidates a repo onto its **real main** and prunes the dead branches AI coding sessions leave behind — without losing work or breaking the deploy. **Protects the branch the VPS deploys from** (never deletes/renames it), classifies every branch (merged → safe-delete / unmerged-with-unique-work → surfaced, never auto-deleted / stale), takes a full `git bundle --all` backup + per-branch backup tags before any deletion, then deletes only provably-merged branches with the safe `git branch -d`. Reversible by design; read-only `audit` mode by default. | [`agents/branch-consolidator/`](agents/branch-consolidator/) |

## How to use an agent

1. **Clone & configure.** `cp .env.example .env` and fill in the keys an agent needs
   (see [`.env.example`](.env.example)). `.env` is gitignored — **never commit it**.
2. **Install [`uv`](https://docs.astral.sh/uv/)** (agents that run Python use it; deps
   auto-install via PEP-723 inline metadata, no venv setup).
3. **Open an LLM session** in the project you want the agent to work on.
4. **Point it at the agent**, e.g.:
   > Read `path/to/agentes_perdidos/agents/image-creator/SKILL.md` and this project's
   > `prompts.md`. Create the missing assets and save them to their expected paths.
5. The agent reads its `SKILL.md` and does the work.

## Layout

```
agentes_perdidos/
├── .env.example          # template — copy to .env, never commit .env
├── README.md             # this file
├── AGENTS.md             # conventions for adding a new agent
└── agents/
    ├── image-creator/    # SKILL.md + imagegen.py
    ├── i18n/            # SKILL.md + translate.py + scan.py + status.py + langs.json
    └── second-brain/    # SKILL.md + secondbrain.py + shared/ (generic base, linked by projects)
```

> **Lost-agent rule:** an agent runs on *any* project and treats that project as its workspace.
> It persists project-specific notes/progress in the **target project's own** brain — the
> `second-brain` LLM-wiki inside that project's Obsidian vault if present, else a `./.<agent>/`
> dir there — **not** in this repo, and only carries *generalizable* learnings back into its own
> `SKILL.md`. See [`AGENTS.md`](AGENTS.md).

## Adding a new agent

See [`AGENTS.md`](AGENTS.md). Short version: make `agents/<name>/`, write a `SKILL.md`
(name + description frontmatter, then how it decides and runs), add any code, list any
new env vars in `.env.example`, and add a row to the table above.

## Secrets

Keys live in `.env` only (gitignored). Each agent documents which keys it needs in its
`SKILL.md`/`README.md` and in `.env.example`. Currently: `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`KLING_ACCESS_KEY`, `KLING_SECRET_KEY`.
