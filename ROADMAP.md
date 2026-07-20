# Roadmap

What is shipped is in the README (the three entity types, the deterministic eval, the enforcement core). This is the planned direction, with the reason for each item and its state, ordered by what deepens the core thesis. The engine is being rebuilt in TypeScript as a strangler over the shared catalog; the design and the delivery sequencing are in [ARCHITECTURE.md](ARCHITECTURE.md), and several items below are reframed by it.

## The TypeScript rebuild

The core loop is built in Python. The move to TypeScript on Bun ([docs/LANGUAGE.md](docs/LANGUAGE.md)) is not a rewrite from zero: the markdown cards are the language-agnostic source of truth, so the Python and TypeScript builds operate on the same catalog and a working system exists at every step. It is sequenced by value per session, not by the dependency graph: knowledge (O2) first, since a saved fact pays off the next session; then the hot enforcement path, the smallest self-contained piece; then preference-enforcement authoring (O1), which depends on accumulated corrections. Full sequencing and the two-runtime coordination model are in [ARCHITECTURE.md](ARCHITECTURE.md), section 10. *In progress.*

## Near-term hardening

- **Check language and evidence-based validation.** The regex matcher path is replaced by a small, auditable check language: lexical checks in front of the call, structural checks at turn end. Checks are validated against recorded tool-call history, not proved symbolically, and the review gate shows a rule's real firing history instead of a rationale. This retires the ReDoS and recursion guard class: a linear-time regex engine removes the backtracking hazard, so there is no catastrophic pattern to guard against. Design in [ARCHITECTURE.md](ARCHITECTURE.md) section 5.1 and [DECISIONS.md](DECISIONS.md). *Designed, part of the rebuild.*
- **ReDoS and recursion guards (Python reference implementation).** *Shipped, being retired.* `precept/safe_regex.py` rejects catastrophic patterns at compile and bounds every match at enforce; the recursion guard stops a nested `claude -p` hook from re-firing. Both stay in the Python build until the check-language seam migrates, after which the linear-time engine makes the ReDoS guard unnecessary.
- **Check-fidelity eval.** The deterministic eval proves the engine is correct over hand-written checks. It does not prove that the check drawn from a correction captures the intent; a too-broad check can pass and over-block. Plan: a per-entry eval that the generated check blocks the violating call and allows a held-out compliant one, closing the gap between "engine correct" and "check correct." *Planned.*
- **Publish the cost model.** The token meter is built; the numbers are not yet surfaced. Plan: report measured per-flow token and latency cost (detection, judgment verdict) and the relevance-gate skip rate, so "a model call per turn" is a measurement, not a worry. *Instrument built, reporting pending.*
- **Contract-drift detection.** Hard enforcement rides Claude Code's unversioned hook and permission contract; a change to the event shape or the block-signaling schema can silently downgrade a rule to a no-op, and because the runtime fails open the break leaves no error. Today's startup check only verifies that hooks are registered and on PATH, not that the wired path still blocks. Plan: a startup and version-triggered check that drives a known-blocked action through the live surface and asserts it is still denied, plus inbound-event validation that records an unparseable event as a health signal instead of a silent allow. *Planned.*

## Coverage and measurement

- **Wire the paired live eval to real sessions.** The paired, CI-aware harness that reports the corrected-behavior delta with a 95% confidence interval is built; connecting it to live agent runs and publishing the delta with its error bars is the next step. The deterministic confusion-matrix number stays the headline until then. *Harness built, live wiring pending.*
- **In-the-wild false-block capture.** Log every hard block and let me flag a wrong one, so precision and coverage become self-collecting signals rather than an assertion. *Planned.*

## Retrieval

- **Earn semantic recall with a number.** Knowledge retrieval is keyword-first (full-text, BM25). Vector embeddings are deferred behind a condition, not skipped: add an embedding index only if a Recall@k eval shows keyword search actually missing on these terse, jargon-dense cards, the regime where single-vector embeddings often underperform keyword. A dense arm, if earned, is brute-force cosine over a few hundred vectors, no SQLite extension. *Gated on an unrun eval.*
- **Close the one conformance gap.** Global conventions currently load always-on rather than just-in-time; the fix is activity-keyed retrieval through the existing knowledge seam, bringing retrieval in line with the finite-context guidance. *Planned, documented in `docs/ANTHROPIC-CONFORMANCE.md`.*

## The remaining entity types (6 of 9)

Three entity types are shipped (Rule, Knowledge note, Convention). The other six ride the same spine and the same review gate, and differ only in their commit target, so each is a bounded addition rather than a new system:

| Type | Commits to | State |
|------|-------------|-------|
| Skill | `.claude/skills/<name>/SKILL.md` | designed |
| Agent persona | `.claude/agents/<name>.md` (hard tool-scope plus soft prompt) | designed |
| Output style | `.claude/output-styles/<name>.md` | designed |
| Slash command | `.claude/commands` / `.claude/skills` | designed |
| MCP / tool config | `.mcp.json` / `mcpServers` | designed |
| Permission profile | `settings.json` `permissions` | partial (import plus clean-ban write-back) |

Order is set by the catalog itself: whichever correction type shows up most in real usage is built next. The catalog is the demand signal.

## Portability (host-drift)

Precept targets Claude Code's hook and settings contract today, behind an adapter. The contract can change, and other agent hosts are starting to expose enforcement surfaces. Plan: keep the catalog and the hard/soft model host-agnostic, and let the adapter compile the same entries to other hosts as they expose deny and gate mechanisms. The typed catalog is the durable asset; the compile target is swappable.

## Distribution

- **MCP server over the catalog and review gate.** *Shipped.* A local stdio MCP server exposes four tools (catalog search, entity show, review pending, review decide), so any local MCP client can drive the human-in-the-loop review conversationally. Optional extra; the core stays lean. Publishing to the official MCP registry is a later step.
- **Claude Code plugin packaging.** *Planned.* Bundle the hooks and the MCP server into one versioned plugin so install becomes one command instead of settings mutation.
