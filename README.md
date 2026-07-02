# Precept

Precept is my personal, self-improving platform for agentic AI processes and data cataloging. It continuously learns from my sessions to improve its data catalog, its defined entities (rules, skills, agent personas, and more), and its processes, through explicit direction, with background learning planned.

## Overview

I work inside Claude Code all day, and every session produces things worth keeping: corrections, preferences, procedures, and the facts my work is about. Left in chat they evaporate. Piled into one memory file they go unread and get followed inconsistently.

I built Precept to capture how I work with an agent, and the data that work operates on, as a durable, typed catalog that improves itself. It has three pillars:

- **Processes** — the ways I work, captured as typed entities I define (rules, conventions, skills, agent personas, and more).
- **Data** — the knowledge and data those processes act on, catalogued for recall and reuse.
- **Self-improving** — a loop that learns from my sessions and proposes refinements to both, for my review.

Deterministic enforcement is one capability inside it, the sharp edge for the few entities that must never break, not the headline.

## Who it is for

One user: me, a heavy Claude Code user with a specific, evolving way of working. Precept is published as the setup I actually run, not as a product for others to adopt. The design assumes a single trusted operator who reviews everything it proposes.

## Goals

1. **Keep my agent aligned to how I work.** My established ways of working carry across sessions, so I stop making the same correction twice.
2. **Catalog my processes and data so nothing evaporates.** Ephemeral corrections and knowledge become a durable, reusable, current catalog.
3. **Improve continuously with little effort.** The system learns from my sessions and proposes refinements; I review rather than author from scratch.

## Non-goals

- **Not a general product.** It is my personal setup, published. I am not building for adoption, packaging, or multi-user use.
- **Not a replacement for Claude Code's native memory.** It complements native memory with a typed, reviewable, cross-tool catalog.
- **Not "enforce everything."** Most entities steer; only the true invariants are hard-enforced. Over-enforcing trains me to turn the tool off.
- **Never silent.** Nothing enters the catalog or takes effect until I approve it.

## How it works

### Processes: the entities I define

Every way I work is captured as a typed entity with a specific home, so a correction lands as the right kind of artifact instead of one more line in a memory file. A router picks the home by the shape of the correction. Nine entity types are defined; three are built:

| # | Entity | Home | Tier | Status |
|---|--------|------|------|--------|
| 1 | Rule | hooks (PreToolUse / Stop / UserPromptSubmit) + `permissions.deny` | HARD | built |
| 2 | Knowledge note | Precept-native FTS5/BM25 index (this is the Data pillar) | SOFT | built |
| 3 | Convention | Precept-owned `.claude/rules/*.md` (global / repo / path-scoped) | SOFT | built |
| 4 | Skill | `.claude/skills/<name>/SKILL.md` | SOFT | designed |
| 5 | Agent persona | `.claude/agents/<name>.md` | HARD tools + SOFT prompt | designed |
| 6 | Output style | `.claude/output-styles/<name>.md` | SOFT | designed |
| 7 | Slash command | `.claude/commands` or `.claude/skills` | SOFT | designed |
| 8 | MCP / tool config | `.mcp.json` / `mcpServers` | config | designed |
| 9 | Permission profile | `settings.json` `permissions` | HARD | partial (import + clean-ban) |

The six designed types ride the same authoring loop and review gate and differ only in where they are written.

### Data: the catalog

The knowledge note (type 2) is the first pillar-2 entity: the facts, context, and references my work is about, stored in a local FTS5/BM25 index and surfaced by relevance when a session needs them. The planned upgrade is a richer typed catalog of the entities my work operates on (projects, domains, people), so the data is structured and reusable rather than freeform.

### Self-improving: the loop

A detect, review, compile loop authors and refines these entities from how I actually work. It always proposes for my review and never applies anything silently. Today it learns from my sessions (explicit direction); drafting from its own reading of best practices is a planned extension.

```
session transcript
      |  Stop / SessionEnd hook (fire-and-forget, fail-CLOSED)
      v
   DETECT   a small model extracts a candidate lesson from genuine user-typed turns; abstains by default.
      v
   COMPILE  the lesson becomes one or more typed entities. Determinism is earned here: an entity
            only becomes hard-enforcing if it compiles to a matcher that passes a typed validator.
      v
   REVIEW   `precept keep` / `precept delete`. Nothing takes effect until I keep it.
      v
   COMMIT   the entity is a markdown card (the source of truth, diffable, sync-safe); the compiled
            cache is disposable and rebuildable from the cards.
```

DETECT fails closed (it abstains rather than guess). Runtime fails open (a missing key or unreadable cache never blocks a session). It is conservative about what it learns and conservative about what it breaks.

### Enforcement: one capability

Most entities steer. The few that are true invariants ("never run `npm`", "run the tests before claiming success") need more than steering, because Claude Code delivers context (`CLAUDE.md`, skills, rules files) to the model as suggestions it follows at its discretion. Only hooks, permission rules, and subagent tool-scoping run outside the model's control. Precept compiles the invariant entities into that deterministic layer so they block rather than nudge.

The honest part is enforced in code, not asserted: an entity is labeled HARD or SOFT, and a validator rejects any HARD entity attached to an event that cannot actually block. So an entity can never claim enforcement it cannot deliver. Invariants that need a judgment ("no stub code") run a deterministic gate with a cheap model verdict, and fail open, a missing key can cost a catch but never wedges a session.

## How I measure it

The enforcement capability is the part I can measure rigorously, so I do, in two tiers that answer different questions.

**Deterministic scorecard.** `precept evals` runs the real enforcement engine over a committed golden set of 25 cases and tallies the confusion matrix. No model call, no variance, CI-gateable.

```
                 predicted block   predicted allow
actual violation      TP = 10          FN = 0
actual compliant      FP = 0           TN = 15

recall 100% (10/10)   false-block rate 0% (0/15)
```

The claim is deliberately bounded: of the violations it has a rule for, it blocks all of them and blocks no compliant call. It does not claim to catch mistakes it has no rule for.

**Paired behavior delta.** Whether enforcement actually keeps my agent aligned (goal 1) is a live, noisy measurement, so it is reported as a paired before/after with a 95% confidence interval, not a single number, because agentic-eval infrastructure noise alone swings scores by several points between identical runs. The reporting harness is built; wiring it to live runs is the next step (see `ROADMAP.md`).

## Status and roadmap

The core loop works end to end (correct, detect, review, keep, then enforce or steer), with 250 offline hermetic tests and a CI-gated deterministic eval. Three of the nine entity types are built; the other six are designed and sequenced. Full planned direction, including the data-catalog upgrade and the background-learning extension, is in `ROADMAP.md`. Built with Claude Code.

## Under the hood

- **Entities are data, never code.** The enforcement engine is a fixed stdlib interpreter over compiled JSON; no `eval` or `exec`. Model-generated regex is length-capped and fails safe.
- **Local-first, sync-safe.** Markdown cards are the source of truth and are safe in a synced vault. The derived index and cache live on local disk only, because SQLite corrupts under cloud sync; the cache is disposable and rebuildable.
- **Atomic, reversible writes.** Every write to `~/.claude` is atomic and backed up; sidecar manifests record exactly what Precept wrote, so uninstall removes only its own entries.
- **Security.** The enforcement hooks are local checks and send nothing off the machine. The learning loop sends transcript excerpts to the model for classification, the same data path as any Claude Code turn; `PRECEPT_DISABLE_DETECT=1` turns it off. Nothing enforces until I keep it.

Engineering decisions with their reasons are in `DECISIONS.md`; the self-audit against Anthropic's agent-rules guidance is in `docs/ANTHROPIC-CONFORMANCE.md`.

## Install

```bash
git clone https://github.com/NoaBarzelay/precept && cd precept
uv venv && uv pip install -e ".[dev]"
pytest -q            # 250 tests, offline and hermetic

precept install                 # wire hooks into ~/.claude (idempotent, atomic, backed up)
precept bootstrap               # seed candidate entities from my existing setup
precept detect <transcript>     # classify a session into a candidate entity
precept list                    # show the catalog
precept keep <id>               # the review gate: keep -> active
precept evals                   # the deterministic scorecard
precept doctor                  # resolved paths, sync-safety check, hook reachability
```

The enforcement engine needs no model. The learning loop does, selected by `PRECEPT_INFERENCE`: the Claude subscription through the local `claude` CLI by default, or the Anthropic SDK with an API key. The client is injected at every seam (a fake client in the tests), so all 250 tests run offline.

## Repository guide

- `DECISIONS.md`: the load-bearing engineering decisions with their reasons.
- `ROADMAP.md`: planned direction (the data-catalog upgrade, background learning, the remaining entity types, hardening).
- `docs/ARTIFACTS.md`: the per-entity spec and status tracker.
- `precept/enforce.py`: the enforcement interpreter.

## License

MIT.
