# Precept

**Your personal, self-improving platform for agentic AI work.** Precept defines and
catalogs the *processes* you run with AI and the *entities and data* they act on, and
improves both continuously by learning from how you actually work, every session.

- **Processes** the reusable ways you get work done with agents (directions, rules,
  skills, personas, workflows). Precept captures, catalogs, and refines them.
- **Entities and data** what your work is about (knowledge, projects, domains, people).
  Precept catalogs what you know so it can be recalled and reused.
- **Self-improving** from two sources: (1) *your work* (every session is an input;
  it learns new processes and entities, sharpens existing ones, retires stale ones),
  and (2) *its own learning* (on its own judgment it reads best practices, checks the
  web, and proposes improvements). It acts with your review, never silently.

One capability inside the process layer is **deterministic enforcement**: the part of a
process that can be checked mechanically is compiled into Claude Code hooks that *block*,
not just suggest. (Claude Code's own docs note that `CLAUDE.md` and skills are "context,
not enforced configuration"; hooks are the only hard layer. Precept labels every artifact
**HARD-enforced** vs **SOFT-steered**, and only claims enforcement for the hard tier.) It
is the sharpest edge of the platform, not the whole of it.

## Why this exists

Agent "memory" captures what you tell it but obeys it ~70% of the time. Precept's
wedge is the part nobody ships: it compiles a correction into a **deterministic,
pre-completion guardrail**. Tell it once "always run the tests before you say it
works," and a later session is *blocked* from claiming success until the tests
actually ran — not nudged, blocked.

## What it compiles a session into (9 artifact types)

| Type | Enforcement |
|------|-------------|
| **Rule** (PreToolUse deny / Stop gate / permission deny / subagent scope) | **HARD** |
| Knowledge note (recalled later) · CLAUDE.md edit · Skill · Output style | soft |
| Agent persona (tool-scoping) | **hard** scope / soft prompt |
| Slash command · MCP config · Permission profile | varies |

Two rule shapes: **single-call** ("never `npm`, use `pnpm`" → PreToolUse) and
**trajectory** ("tests before done" → Stop hook). Judgment rules ("don't leave
stub code") run a small LLM verdict *at* a deterministic gate — the gate blocks,
the verdict is auditable as the prompt on the card.

## Architecture

```
session transcript
      │  Stop / SessionEnd hook (async, fail-closed)
      ▼
   DETECT  ── Anthropic SDK structured extraction (Haiku) → MaybeLesson (abstain-aware)
      ▼
   COMPILE ── Lesson → 1..N typed Policy (Cedar-style), determinism earned here
      ▼
   REVIEW  ── `precept keep/delete` — the human gate; nothing enforces until kept
      ▼
   COMMIT  ── markdown card (source of truth) + compiled policies.json (hot path)
      ▼
   ENFORCE ── PreToolUse / Stop hooks read the JSON cache (stdlib only, fast)
```

**Local-first, by design.** Markdown cards are the source of truth (safe to keep
in a synced vault; git is the audit log). The derived SQLite index / policy cache
lives on a **local** disk (`~/.local/state/precept`), never a cloud-synced folder —
SQLite corrupts under sync. Every write to your real `~/.claude` / vault is atomic.

**Rules are data, never code.** `precept.enforce` is a fixed, hardened interpreter
over compiled policy JSON; it never `eval`s a generated rule.

## Status

Early but the core loop is real and tested (22 tests). Working today:

```bash
precept install                 # wire Precept's hooks into ~/.claude (idempotent, backed up)
precept bootstrap               # seed from your existing setup (permission rules + CLAUDE.md)
precept detect <transcript>     # classify a session, mint a PENDING lesson from a correction
precept list                    # see the catalog
precept keep <id>               # the human gate: PENDING -> ACTIVE; deterministic ones auto-compile
precept note "X" --body "..."   # capture a knowledge note; precept recall "query" to find it later
precept evals                   # the deterministic scorecard (100% recall, 0 false-blocks)
# ...next session, the PreToolUse/Stop hook BLOCKS the thing you corrected.
```

The whole loop is wired: **correct → DETECT (mint pending) → keep (auto-synthesize
a matcher) → ENFORCE (block it next session).** Shipped: the typed spine
(`models.py`), the markdown catalog, COMPILE + **matcher synthesis** (lesson →
enforcing Policy, fail-closed), the **stdlib enforcement matcher** (single-call +
trajectory), the verified Claude Code hook adapter, DETECT (Haiku structured
extraction, abstain-aware), `install`/`uninstall`, and the `precept` CLI review gate.

Plus **Phase-0 bootstrap** (`precept bootstrap`): your `permissions.deny` rules
compile straight into HARD policies, and your CLAUDE.md directives import as soft
lessons to review — so Precept boots already knowing your setup.

## Evals (the part that makes the number trustworthy)

`precept evals` runs a **deterministic, zero-variance confusion matrix** over a
committed golden set of enforcement cases, and CI gates it (`--strict`):

```
recall (violations caught):   100%  (TP=5 FN=0)
false-block rate (compliant):   0%  (FP=0 TN=7)
```

That's the honest claim — *100% of the violations it has a rule for, with no
false-blocks on compliant calls* — not a single dramatic before/after number. The
live before/after (Tier-2) is reported as a **paired, multi-trial delta with a 95%
CI** (`evals/live.py`), because infra noise alone swings agentic eval scores by
several points.

Judgment rules now enforce too: a judgment lesson compiles to a Stop **verdict
gate** — the gate is deterministic (our hook fires every time), and a cheap Haiku
`{ok, reason}` call decides if the rule was met, lazy-loaded so the deterministic
path stays stdlib, and **fail-open** (a missing key never wedges a session).

Knowledge recall ships too: `precept note` / `precept recall` store notes as
markdown (source of truth) and search them with SQLite **FTS5/BM25** + tag filtering.
The index lives on a local disk (never the synced vault) and is fully rebuildable
from the markdown (`precept reindex`). Semantic/vector recall (sqlite-vec) is a
deliberate *later* add — only if a Recall@k eval shows keyword search missing things.

Next: the live Tier-2 agent runs, and the P4 extras (output styles, slash commands,
MCP config, permission profiles).

## Develop

```bash
uv venv && uv pip install -e ".[dev]"
pytest -q
precept doctor      # show resolved paths + the iCloud-safety check
```

License: MIT.
