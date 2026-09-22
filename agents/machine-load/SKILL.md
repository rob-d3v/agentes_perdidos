---
name: machine-load
description: >
  Answers "why is this PC slow / out of RAM right now, and is something improper running?" —
  the runtime sibling of disk-audit and faxineiro, which answer the same question about DISK.
  Enumerates every process, groups them into families (AI/agent tooling, browser, editor,
  containers, system, antivirus) so the report says "AI tooling: 9.4 GB" instead of forty lines
  the reader has to add up, flags accumulation (many instances of one program, instances idle
  for hours), and turns that into advice with a number attached: "10 of 35 `claude` processes
  have been idle over 4h, ~149 MB each — closing the old sessions returns ~1.5 GB". Explicitly
  refuses to suggest closing system or antivirus processes, and NEVER kills anything itself.
  Use when RAM or CPU is pegged, when the machine got slow and nobody knows why, when deciding
  whether it is safe to dispatch more parallel agents, or to rule out that something improper
  is running. Windows-first, stdlib only, degrades to /proc on Linux.
---

# machine-load — where the memory went

You answer three questions, in this order, and you never skip to the third:

1. **Is something improper running?** — usually no, and saying so plainly is the answer.
2. **Where did the memory actually go?** — by family first, then by program.
3. **What is safe to close, and how much does it give back?** — with a number.

## Why this exists

A 16 GB workstation hit **95% RAM with 0.7 GB free** during a long AI-assisted session. The
owner's reasonable suspicion was that something improper was running. It was not. It was
**32 `claude` (4.4 GB), 8 `node` (2.4 GB), 18 `chrome` (1.8 GB), and 123 small
`python`/`bash`/`conhost` processes** — agent tooling accumulating faster than anything reaped
it. Ten of the Claude sessions had been idle for more than four hours.

Nothing was broken. Nobody had printed the list.

That is the whole job: print the list, grouped so a human can act on it.

## Run it

```bash
python load.py                 # the report
python load.py --top 25        # deeper program list
python load.py --stale 240     # what counts as "idle", in minutes
python load.py --json          # machine-readable
```

Stdlib only, Python 3.8+. No install, no `psutil`.

## Two rules that are not negotiable

**It never kills anything.** A process list is a terrible basis for automated killing: the
single biggest consumer is routinely the editor holding unsaved work. The agent reports and
the human closes.

**It never suggests closing system or antivirus processes.** The first version of this tool
cheerfully advised *"83 of 84 `svchost` processes have been idle over 240 min — closing them
returns ~0.9 GB"*. `svchost` is the Windows service host; that advice is actively harmful. An
"idle for hours" signal only means waste for processes the **user** opened. `NEVER_SUGGEST`
enforces this, and the exclusion is checked before any tip is generated.

## Reading the output

The **family** table is the honest headline — it is what lets someone say "my AI tooling is
using more than half this machine" instead of scrolling. The **program** table is where the
action is, with an instance count and an idle count.

An instance count of 25+ for one program is almost never real use; it is tooling that spawns
and does not reap. The report says so, and says to find what creates them rather than to
close them one by one.

## Companion agents

- `disk-audit` / `faxineiro` — the same question about disk space. Run those when the
  complaint is "no space"; run this one when the complaint is "slow" or "out of memory".
- `worktree-janitor` — reclaims disk taken by leftover git worktrees, another accumulation
  problem with the same shape: nobody had listed them.

## Before dispatching parallel agents

This is the pre-flight check. Under ~80% memory, dispatching more is fine. Above it, each new
agent buys latency instead of throughput, and past ~95% the machine starts swapping and
everything — including the agents already running — gets slower. Read the number first.
