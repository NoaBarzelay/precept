# Precept

**Status:** living document · **Owner:** Noa Barzelay · **Last updated:** 2026-07-02

## Summary

Precept is my personal, self-improving platform for agentic AI processes and data cataloging. It continuously learns from my sessions to improve its data catalog, its defined entities (rules, skills, agent personas, and more), and its processes, through explicit direction, with background learning planned.

## Problem

Claude Code is my primary development agent. Working with it produces durable assets: corrections, procedures, preferences, and the knowledge and data my work operates on. Claude Code's native mechanisms hold these as freeform context. Chat history is discarded per session. Memory files accrete into a single document that is loaded whole and followed at the model's discretion, with no compliance guarantee. The result is repeated corrections, no structured catalog of processes or data, and no improvement loop.

## Goals and success metrics

| # | Goal | Success metric |
|---|------|----------------|
| G1 | Keep my agent aligned to how I work | Corrected-behavior delta with enforcement on vs off, measured as paired trials with a 95% CI (`evals/live.py`); deterministic scorecard at 100% recall, 0 false-blocks on the committed golden set |
| G2 | Catalog my processes and data so nothing evaporates | Every kept correction lands as a typed entity with a defined commit target; the catalog stays current through decay and supersede governance |
| G3 | Improve continuously with low effort | My workflow is review-only: keep or delete proposals; no hand-authoring of configuration |

## Non-goals

- **A general product.** This is my setup, published. No packaging, onboarding, or multi-user support.
- **A replacement for Claude Code's native memory.** Precept complements it with a typed, reviewable catalog.
- **Enforce everything.** Most entities steer. Only true invariants are hard-enforced; over-enforcement produces false blocks and gets a tool turned off.
- **Autonomous action.** Nothing enters the catalog or takes effect without my explicit approval.

## Users and environment

- One user: me, a single trusted operator who reviews every proposal.
- Runtime: Claude Code on a local machine. Precept registers five hooks and a CLI.
- Inference: the learning loop uses my Claude subscription through the local `claude` CLI, or the Anthropic SDK with an API key (`PRECEPT_INFERENCE`). The enforcement runtime uses no model.

## System overview

Three pillars:

- **Processes**: the ways I work with an agent, captured as typed entities I define (rules, conventions, skills, agent personas, and more).
- **Data**: the knowledge and data those processes act on, catalogued for recall and reuse.
- **Self-improving**: a loop that learns from my sessions and proposes refinements to both, for my review.

```
session transcript
      |  Stop / SessionEnd hook (fail-CLOSED)
      v
   DETECT    a small model extracts a candidate lesson from genuine user-typed turns; abstains by default
      v
   COMPILE   the lesson becomes one or more typed entities; an entity only becomes hard-enforcing
             if it compiles to a matcher that passes a typed validator
      v
   REVIEW    `precept keep` / `precept delete`; nothing takes effect until kept
      v
   COMMIT    markdown cards are the source of truth; the compiled cache is derived and rebuildable
      v
   runtime   hooks read the cache and enforce (HARD) or inject context (SOFT); stdlib only, fail-OPEN
```

## Functional requirements

Status: **built** (implemented and tested), **partial** (subset implemented), **designed** (specified, not implemented), **planned** (roadmapped).

### R1: Processes

| # | Requirement | Status |
|---|-------------|--------|
| R1.1 | Every kept correction compiles to a typed entity with a defined commit target | built |
| R1.2 | Nine entity types are supported (table below) | 3 built, 1 partial, 5 designed |
| R1.3 | A router assigns each correction to the right entity type by its shape | partial |
| R1.4 | Entities are scoped (global, repo, language, path) and load accordingly | built |

| Entity | Commit target | Tier | Status |
|--------|---------------|------|--------|
| Rule | hooks + `permissions.deny` | HARD | built |
| Knowledge note | local FTS index (the Data pillar) | SOFT | built |
| Convention | `.claude/rules/*.md` | SOFT | built |
| Skill | `.claude/skills/<name>/SKILL.md` | SOFT | designed |
| Agent persona | `.claude/agents/<name>.md` | HARD tools + SOFT prompt | designed |
| Output style | `.claude/output-styles/<name>.md` | SOFT | designed |
| Slash command | `.claude/commands` / `.claude/skills` | SOFT | designed |
| MCP / tool config | `.mcp.json` / `mcpServers` | config | designed |
| Permission profile | `settings.json` `permissions` | HARD | partial |

### R2: Data

| # | Requirement | Status |
|---|-------------|--------|
| R2.1 | Knowledge is captured from sessions and stored in a local, rebuildable index | built |
| R2.2 | Relevant knowledge is injected at prompt time, selected by relevance | built |
| R2.3 | A typed catalog of the entities my work operates on (projects, domains, people) | planned |

### R3: Self-improving

| # | Requirement | Status |
|---|-------------|--------|
| R3.1 | Candidate entities are detected from session transcripts, abstain-biased | built |
| R3.2 | Nothing takes effect without an explicit keep | built |
| R3.3 | Governance keeps the catalog current: decay, supersede, conflict detection | built |
| R3.4 | Background learning drafts proposals from external best practices | planned |

### R4: Enforcement

| # | Requirement | Status |
|---|-------------|--------|
| R4.1 | Invariant entities compile to deterministic enforcement (hooks, permission rules, subagent tool-scoping) | built |
| R4.2 | Invariants with no mechanical check run a model verdict at a deterministic gate | built |

## Non-functional requirements

| # | Quality | Requirement | Status |
|---|---------|-------------|--------|
| N1 | Reliability | The runtime fails open: no error, missing key, or unreadable cache ever blocks a session | built |
| N2 | Performance | The enforcement hot path is stdlib-only: no model call, no network | built |
| N3 | Security | Model-authored logic executes only as data; regex is ReDoS-guarded at compile and runtime; nested inference is recursion-guarded | built |
| N4 | Integrity | An entity cannot claim enforcement it cannot deliver; the HARD/SOFT boundary is validated in the type system | built |
| N5 | Reversibility | All writes to `~/.claude` are atomic, backed up, and exactly inverse on uninstall | built |
| N6 | Testability | The model client is injectable at every seam; the full suite runs offline and hermetic | built |
| N7 | Privacy | Local-first: enforcement sends nothing off the machine; the learning loop is disabled by one env var | built |

## Measurement

Two tiers, answering different questions.

**Tier 1, deterministic scorecard.** `precept evals` runs the real enforcement engine over a committed golden set of 25 cases and tallies the confusion matrix. No model call, no variance, CI-gated.

```
                 predicted block   predicted allow
actual violation      TP = 10          FN = 0
actual compliant      FP = 0           TN = 15

recall 100% (10/10)   false-block rate 0% (0/15)
```

The claim is bounded: of the violations it has a rule for, it blocks all of them and blocks no compliant call.

**Tier 2, paired behavior delta.** Whether enforcement keeps the agent aligned (G1) is a live measurement, reported as a paired before/after with a 95% CI, because agentic-eval infrastructure noise alone shifts scores by several points between identical runs. The reporting harness is built; live wiring is the next milestone.

## Milestones and status

- **Done:** the core loop end to end (detect, review, keep, enforce or steer); 3 of 9 entity types; the deterministic eval, CI-gated; 255 offline hermetic tests; ReDoS and recursion guards.
- **Next:** live wiring of the Tier-2 eval; a compile-fidelity eval (does the generated matcher capture the correction); the token cost report.
- **Planned:** the typed data catalog (R2.3); background learning (R3.4); the remaining entity types, ordered by which correction types show up most in real usage.

Details in `ROADMAP.md`. Built with Claude Code.

## Open questions

- **Semantic recall.** Keyword retrieval (FTS/BM25) may miss fuzzy knowledge. Embeddings are added only if a Recall@k eval shows keyword search actually missing on this corpus; the threshold is not yet set.
- **Router precision.** When a correction is ambiguous between homes (rule vs convention vs skill), what confidence gates auto-routing versus asking.
- **Background-learning trust.** How autonomous reading proposes entities without polluting the catalog; the review gate is necessary but may not be sufficient at volume.
- **Coverage.** How to measure the corrections that never became entities (misses), not just the accuracy of the ones that did.

## Design references

- `ARCHITECTURE.md`: module map and data flow.
- `DECISIONS.md`: the load-bearing engineering decisions with their reasons.
- `docs/ARTIFACTS.md`: the per-entity specification and status tracker.
- `docs/ANTHROPIC-CONFORMANCE.md`: self-audit against Anthropic's agent-rules guidance, including the one open retrieval gap.

## Install

```bash
git clone https://github.com/NoaBarzelay/precept && cd precept
uv venv && uv pip install -e ".[dev]"
pytest -q            # 255 tests, offline and hermetic

precept install                 # wire hooks into ~/.claude (idempotent, atomic, backed up)
precept bootstrap               # seed candidate entities from an existing setup
precept detect <transcript>     # classify a session into a candidate entity
precept list                    # show the catalog
precept keep <id>               # the review gate: keep -> active
precept evals                   # the deterministic scorecard
precept doctor                  # resolved paths, sync-safety check, hook reachability
```

## License

MIT.
