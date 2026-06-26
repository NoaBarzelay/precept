# Precept

**Policy-as-code for your coding agent.** Precept turns the corrections and
learnings from a Claude Code session into durable, auditable artifacts — and
**hard-enforces** the deterministic subset, so a rule you set once is actually
obeyed instead of softly remembered.

> Claude Code's own docs are blunt: `CLAUDE.md`, skills, and memory are *"context,
> not enforced configuration… no guarantee of strict compliance."* Only **hooks**,
> **permission-deny rules**, and **subagent tool-scoping** truly enforce. Precept
> compiles the enforceable subset of your corrections down to those, and labels
> everything else honestly as **soft-steered**.

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
precept detect <transcript>     # classify a session, mint a PENDING lesson from a correction
precept list                    # see the catalog
precept keep <id>               # the human gate: PENDING -> ACTIVE, recompiles the enforcer
# ...next session, the PreToolUse/Stop hook BLOCKS the thing you corrected.
```

The whole loop is wired: **correct → DETECT (mint pending) → keep (auto-synthesize
a matcher) → ENFORCE (block it next session).** Shipped: the typed spine
(`models.py`), the markdown catalog, COMPILE + **matcher synthesis** (lesson →
enforcing Policy, fail-closed), the **stdlib enforcement matcher** (single-call +
trajectory), the verified Claude Code hook adapter, DETECT (Haiku structured
extraction, abstain-aware), `install`/`uninstall`, and the `precept` CLI review gate.

Next: Phase-0 bootstrap (import your existing `~/.claude` + notes as seed rules),
the knowledge index (FTS5 first), judgment-rule (`type: prompt`) hooks, and the
eval harness.

## Develop

```bash
uv venv && uv pip install -e ".[dev]"
pytest -q
precept doctor      # show resolved paths + the iCloud-safety check
```

License: MIT.
