# Roadmap

What is shipped is in the README (the three entity types, the deterministic eval, the enforcement core). This is the planned direction, with the reason for each item and its current state. It is ordered by what deepens the core thesis, not by what is easiest.

## Near-term hardening

- **ReDoS guard on model-generated matchers.** *Shipped.* `precept/safe_regex.py` adds two layers: `looks_catastrophic` rejects nested-quantifier and over-long patterns at COMPILE (a Condition validator refuses them before they enter the catalog), and `safe_search` runs every match under a wall-clock bound at ENFORCE, so a catastrophic-backtracking pattern fails safe (no match, never blocks) instead of stalling the hook. Same threat class as the recursion guard: model output can never harm the machine.
- **A COMPILE-fidelity eval.** The deterministic eval proves the enforcement engine is correct over hand-written policies. It does not yet prove that the matcher the model *generates* from a correction faithfully captures the intent, a too-broad pattern can pass the validator and over-block. Plan: a per-lesson eval that checks the generated policy blocks the violating call and allows a held-out compliant one. This closes the gap between "engine correct" and "compiler correct." *Planned.*
- **Publish the cost model.** The token meter (`precept tokens`) is built; the numbers are not yet surfaced. Plan: report measured per-flow token and latency cost (DETECT, judgment verdict) and the relevance-gate skip rate in `DECISIONS.md`, so "a model call per turn" is a measurement, not a worry. *Instrument built, reporting pending.*

## Coverage and measurement

- **Wire the paired live eval (Tier 2) to real sessions.** The paired, CI-aware harness that reports corrected-behavior delta with a 95% CI is built (`evals/live.py`); connecting it to live agent runs and publishing the delta with its error bars is the next step. The deterministic Tier-1 number stays the headline until then. *Harness built, live wiring pending.*
- **In-the-wild false-block capture.** Log every HARD block and let the user flag a wrong one, so precision and coverage become self-collecting signals rather than an assertion. *Planned.*

## Retrieval

- **Earn semantic recall with a number.** Knowledge retrieval is keyword-first (FTS5/BM25). Vector embeddings are deferred behind a condition, not skipped: add sqlite-vec only if a Recall@k eval shows keyword search actually misses on these terse, jargon-dense cards (the regime where single-vector embeddings often underperform keyword). *Gated on an unrun eval, deliberately.*
- **Close the one conformance gap.** Global conventions currently load always-on rather than just-in-time; the fix is activity-keyed retrieval through the existing knowledge seam, bringing retrieval in line with the finite-context guidance. *Planned, documented in `docs/ANTHROPIC-CONFORMANCE.md`.*

## The remaining entity types (6 of 9)

Three entity types are shipped (Rule, Knowledge note, Convention). The other six ride the same `Lesson` spine and the same keep/veto gate, and differ only in their COMMIT target, so each is a bounded addition rather than a new system:

| Type | Compiles to | State |
|------|-------------|-------|
| Skill | `.claude/skills/<name>/SKILL.md` | designed |
| Agent persona | `.claude/agents/<name>.md` (HARD tool-scope + SOFT prompt) | designed |
| Output style | `.claude/output-styles/<name>.md` | designed |
| Slash command | `.claude/commands` / `.claude/skills` | designed |
| MCP / tool config | `.mcp.json` / `mcpServers` | designed |
| Permission profile | `settings.json` `permissions` | partial (import + clean-ban write-back) |

Order is set by the catalog itself: whichever correction type shows up most in real usage is built next. The catalog is the demand signal.

## Portability (host-drift)

Precept targets Claude Code's hook and settings contract today, behind an adapter (`adapters/`). The contract can change, and other agent hosts are starting to expose enforcement surfaces. Plan: keep the catalog and the HARD/SOFT model host-agnostic, and let the adapter compile the same lessons to other hosts as they expose deny/gate mechanisms. The typed catalog is the durable asset; the compile target is swappable.

## Distribution

- **MCP server over the catalog and review gate.** *Shipped.* `precept mcp` runs a local stdio MCP server (`precept/mcp_server.py`) with four tools (catalog_search, entity_show, review_pending, review_decide), so any local MCP client can drive the human-in-the-loop review conversationally. Optional extra (`precept[mcp]`); the core stays at four runtime dependencies. Publishing to the official MCP registry is a later step.
- **Claude Code plugin packaging.** *Planned.* Bundle the hooks and the MCP server into one versioned plugin so install becomes `claude plugin install precept` instead of settings mutation.
