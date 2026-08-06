# habitar — the anti-ghost-town agent

Your product is live. Nobody is there. The grids are empty, the community links go nowhere, and
the one thing that would actually help — visible proof that other humans use this — is the one
thing you can't have yet.

The obvious shortcut is to fake it. **This agent won't, and the first thing it will do is show
you why the honest version wins anyway.**

> **The one rule:** `habitar` never creates a person, an opinion, or a number that did not happen.

Person / opinion / number covers every astroturfing request: fake accounts, fake reviews and
votes, inflated counters. Ask for one and the agent names the rule, cites the law, and hands you
the nearest legitimate substitute — that last part is the point, not the refusal.

## What it actually does

A product with no customers has two problems that look like one. Everyone assumes it's *"nobody
is here."* Usually the bigger half is *"it is not presented as though anybody is."* Only one of
those needs users you don't have yet.

On its first real run against a live marketplace, `habitar` found:

- three homepage sections stacked on top of each other where **two rendered the identical array** —
  21 real listings displayed as if there were 4;
- `aggregateRating 4.8 / ratingCount 50` hardcoded in JSON-LD with no ratings behind it;
- a `sameAs` claim pointing at a GitHub org that **returns 404**;
- four "use case" videos all set to the Rick Astley video ID, in production;
- and — from crawling the public API as an anonymous visitor — **an unauthenticated endpoint
  serializing whole user records**: emails, OAuth ids, payment customer ids, including a real
  third-party seller's.

None of that needed more users to fix. That is the thesis.

## Files

| File | Role |
|---|---|
| `SKILL.md` | The brain. Modes, the PERMITTED/DISCLOSE/FORBIDDEN matrix, the scoring model, the traffic rule. Read this one. |
| `liveness.py` | Crawls declared surfaces as an anonymous visitor, scores the liveness ledger, leak-scans every JSON response. |
| `promises.py` | Placeholder scan + live outbound verification + the substantiation lint. `--strict` exits 1, so it works in CI. |
| `example.habitar.json` | Annotated config template. All stack knowledge lives here; the scripts are framework-blind. |

## Quickstart

```bash
# 1. Draft a config from the site's sitemap, then EDIT it — it cannot know your selectors.
uv run agents/habitar/liveness.py --init https://example.com --out app.habitar.json

# 2. Lint the promises the site makes (dead links, placeholders, unsubstantiated numbers).
uv run agents/habitar/promises.py --config app.habitar.json --root /path/to/repo \
    --out .habitar/promises.json

# 3. Score how inhabited it looks. --promises feeds the honesty multiplier.
uv run agents/habitar/liveness.py --config app.habitar.json \
    --promises .habitar/promises.json --out .habitar/liveness.json

# 4. Later, after changes — this is what makes a claimed win checkable.
uv run agents/habitar/liveness.py --config app.habitar.json --baseline .habitar/liveness.json
```

## The scoring model, briefly

Five dimensions per surface — **P**opulation (log-scaled: 0→1 item is the big jump), **V**ariety
(catches "three different sections, same array"), **A**ctivity (staleness, not just count),
**C**ontinuity (dead ends), **I**nvitation (a surface with *zero items* but a real "be the first"
and a capture point scores full marks here — that's the whole thesis) — then an **honesty
multiplier** `H`: `1.0` clean, `0.5` any unsubstantiated claim, `0.0` any fabricated person.

`H` exists because you are handing an LLM a number to maximize, and if lying raises the number it
will eventually lie. With `H`, a surface that looks inhabited *because it lies* always scores
below an honestly empty one.

Static pages (no data-backed sections) are scored only on the dimensions that apply and
renormalized — a FAQ is not a ghost town for having no database rows.

## Two things that will surprise you

**It will tell you not to use it.** Every report prints sessions/week first. Below the floor
(default 50) the agent refuses to rank storefront work above distribution and says so in one
line. Doubling conversion on 300 lifetime visits produces no customers. Storefront work is
insurance that traffic someone *else* brings doesn't bounce.

**It never deletes anything.** Every dead link is a promise to fulfil, not something to erase:
create the profile, build the destination, or convert it into a disclosed "coming soon — notify
me" capture (which is also an `invite` win). Deleting a dead link to raise the liveness score is
gaming the metric, and `promises.py` says so in its own output.

## What it hands off

Distribution (ads, outreach, communities, directories) and creating the social profiles your
`sameAs` already claims exist — those belong to whoever owns those accounts. `habitar` emits the
exact list of URLs that must become true; it doesn't act on them.
