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
| **design-reviewer** | Senior product-designer agent. Diagnoses what looks amateurish in a UI and produces a professional, buildable redesign/refactor plan (layout, hierarchy, color, motion, window chrome, branding/mascot) that preserves all functionality, plus an AI-asset spec routed to image-creator. Audits which assets are actually used. | [`agents/design-reviewer/`](agents/design-reviewer/) |
| **llm-wiki** | Personal knowledge-base librarian (Karpathy "LLM Wiki" pattern). Incrementally builds and maintains a persistent, interlinked markdown wiki from raw sources — ingest, query, lint. | [`agents/llm-wiki/`](agents/llm-wiki/) |

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
    └── llm-wiki/         # SKILL.md + index.md + log.md + raw/ + wiki/
```

## Adding a new agent

See [`AGENTS.md`](AGENTS.md). Short version: make `agents/<name>/`, write a `SKILL.md`
(name + description frontmatter, then how it decides and runs), add any code, list any
new env vars in `.env.example`, and add a row to the table above.

## Secrets

Keys live in `.env` only (gitignored). Each agent documents which keys it needs in its
`SKILL.md`/`README.md` and in `.env.example`. Currently: `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`KLING_ACCESS_KEY`, `KLING_SECRET_KEY`.
