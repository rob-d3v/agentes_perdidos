---
title: habitar agent
type: entity
created: 2026-08-06
updated: 2026-08-06
sources: [agents/habitar/SKILL.md, agents/habitar/liveness.py, agents/habitar/promises.py, agents/habitar/example.habitar.json]
tags: [agent, cold-start, growth, honesty, empty-state, marketplace, ftc, cdc, lgpd]
---

The **anti-ghost-town** agent. Makes a launched-but-empty product look **and be** inhabited, without fabricating social proof. Built 2026-08-06; first real run against a live avatar marketplace.

> **The one rule** (lives in the frontmatter `description` on purpose — the only part guaranteed in context on every trigger): *`habitar` never creates a person, an opinion, or a number that did not happen.*

"Person / opinion / number" covers every astroturfing request in one line: fake accounts, fake reviews and votes, inflated counters. If the LLM reads nothing else, it cannot drift.

## Origin

Written as the honest replacement for a request to build a "fake prod" agent — one that would create fake users, comments, votes and purchases directly in a production database to simulate traction. Declined: fabricated social proof shown to buyers is deceptive under **CDC art. 37 §1º** (BR), **FTC 16 CFR Part 465** (US, 2024 — fake/AI reviews, insider reviews, bought sentiment), **UCPD Annex I ¶22-23b** (EU), and Google's structured-data policy. It also destroys the owner's only instrument: with seeded rows in prod you can never again answer "did that change work?"

The reframe that made it work: **an app is rarely empty — it is misrepresented in both directions.** It hides the real content it has, while asserting proof it doesn't.

## The thesis

Two problems that look like one. Everyone assumes *"nobody is here."* Usually the bigger half is *"it is not presented as though anybody is."* Only one of those requires users you don't have yet.

## Modes — 5 + 1 gate

| id | PT-BR gloss | owns |
|---|---|---|
| `audit` | levantamento | anonymous crawl, code map, promises, leak scan |
| `surface` | consertar a vitrine | dedupe, light up dark features, static-safe content already shipped |
| `invite` | convite | empty state → first action; **true** scarcity only |
| `return` | caminho de volta | owned-audience capture: digest, changelog, RSS, notify-me |
| `supply` | povoar com o que é nosso | disclosed first-party catalog; `--demo-env` recipe |
| *(gate)* `measure` | régua | analytics + baseline; **blocks** the other four |

`measure` is a **gate, not a mode** — as mode #6 it would be skipped every run. Escape hatch defined so it can't deadlock: a baseline is any reproducible number, and `liveness.json` is one. Analytics is required only for traffic/conversion claims, never structural ones.

## The liveness ledger

Five dimensions per surface: **P**opulation `30·min(1, ln(1+n)/ln(1+target))` (log-scaled — 0→1 item is the enormous jump) · **V**ariety `20·(unique/rendered)·(1−mean_overlap)` (catches "three sections, same array") · **A**ctivity `20·exp(−days/30)` · **C**ontinuity `15 − 3·dead − 3·placeholder − 4·outbound404` · **I**nvitation `5·empty_state + 5·CTA + 5·capture`.

Then the **honesty multiplier `H`** — `1.0` clean, `0.5` any unsubstantiated claim, `0.0` any fabricated person. `H` exists because *you are handing an LLM a number to maximize; if lying raises the number, it will eventually lie.* With `H`, a surface that looks inhabited **because it lies** always scores below an honestly empty one. Without it the model is an astroturfing incentive with extra steps.

Only **N=real** is measured. **N=0** and **N=target** are *modelled* by substituting `n` — stated loudly in every report so nobody empties a prod DB to obtain the N=0 column. Static surfaces (no data-backed sections) are scored only on applicable dimensions and renormalized — same "N/A ≠ fail" lesson as [[ai-visibility]]'s content-type adapter.

## The rule that outranks everything else in the file

Every report prints **sessions/week** first. Below `thresholds.sessions_per_week_floor` (default 50) the agent **refuses to rank `surface` above the distribution handoff**. Doubling conversion on 300 lifetime visits yields no customers; storefront work is *insurance that traffic someone else brings doesn't bounce*. Without this rule the owner polishes an empty store for three weeks and concludes the agent doesn't work.

`--portfolio` ranks N apps by `liveness × traffic` and **names the ones to let die** — triage is the highest-value output for someone maintaining more products than they have customers. Hard cap: **≤5 actions per run**, each with an hour estimate, plus a mandatory "if you only do one thing this week" line.

## PERMITTED / DISCLOSE / FORBIDDEN

Three tiers, not two — a binary matrix makes the agent timid because everything interesting lands in the grey. Axes: identity & authorship · numbers & claims · links & placeholders · demo & synthetic data · distribution.

**Disclosure has a mechanical definition** (this is where an LLM cheats — it "discloses" in a tooltip): same viewport · not behind hover/tooltip/modal/expander · same language · **present in the server-rendered HTML**, not injected by JS. That last clause is the tie to [[ai-visibility]] — a crawler that doesn't run JS sees the claim without the caveat.

Load-bearing rows: a brand may **speak** but may not **applaud itself wearing a customer's face** · owner posting the first real forum question under a real identity is ✅, under an invented persona is 🔴 · *incentivize participation, never sentiment* · every on-screen number needs a `data_source` or it is UNSUBSTANTIATED · **deleting a dead link to raise the score is forbidden** · running a seeder against prod is 🔴 **ABSOLUTE — the operator cannot authorize it**.

**REFUSE + OFFER protocol:** on any 🔴, three things in one response — name the row + citation, offer the nearest ✅ substitute *concretely*, log the request. Step 2 is what stops the owner routing around the agent.

## Framework blindness

> habitar's scripts are framework-blind. All stack knowledge lives in `habitar.json`, which the LLM writes during `audit`.

The moment a script introspects React Router or `urls.py` you maintain three adapters and the agent dies at app #3. Corollary: `liveness.py --init <base_url>` (seeds a draft config from `sitemap.xml`) is survival, not a nicety — nobody hand-writes twelve configs.

## Commands ([[uv]] / PEP-723)

- `uv run agents/habitar/liveness.py --init <url> --out app.habitar.json` — draft config from sitemap.
- `uv run agents/habitar/promises.py --config app.habitar.json --root <repo> --out .habitar/promises.json` — `--strict` exits 1, so it runs in CI.
- `uv run agents/habitar/liveness.py --config app.habitar.json --promises .habitar/promises.json --out .habitar/liveness.json`
- `... --baseline .habitar/liveness.json` — before/after as a first-class operation.
- `--rendered-cmd '<cmd> {url}'` plugs any headless renderer; without it `rendered` falls back to `raw` and the ledger says so rather than pretending.

## The leak scan (the highest-value accident)

Crawling public endpoints as an anonymous visitor is exactly how you find an API serializing whole user records to the open internet. On the very first run it found an unauthenticated listings endpoint returning `email`, `googleId`, `stripeCustomerId`, `role` and moderation internals for every seller — including a real third-party's. Values are always **redacted** in artifacts (shape only). Report it before any liveness finding; an app empty of people while over-exposing the few it has is the inverse failure mode.

## Division of labor

- **[[ai-visibility]]** — declared seam in both descriptions: *ai-visibility asks whether the crawler can read it; habitar asks whether there is anything there to read.* Without it the router picks the wrong agent half the time.
- **Distribution and social-profile creation** — handed off, never performed. habitar emits the exact list of URLs that must become true.
- Per [[lost-agent-rule]], findings persist in the **target project's** brain; machine artifacts in a gitignored `./.habitar/`. Never here. See [[agentes-perdidos]].

## Env keys

None. Both scripts are HTTP + static analysis. `auth.token_env` in the config names an env var when a surface needs a session — key **names** only, never values.
