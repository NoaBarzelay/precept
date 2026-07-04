# Precept

## Context

When I work with an agentic coding assistant, every session starts cold: the way I want my work done and the knowledge my work depends on both reset when the session ends. So each time I re-explain preferences I have already stated and re-supply facts I have already given, and the effort I spent teaching the assistant is spent again rather than compounding. Precept is the system I built to keep both from resetting.

## Goal

A personal platform that, on its own, learns and keeps improving both how I want my agentic AI work done and the knowledge my work depends on, so the two compound across sessions instead of resetting each time.

**Key assumption.** The whole platform rests on one bet: that my ordinary session activity (corrections, requests, discussion, style) carries enough signal to learn my preferences and the knowledge my work depends on, without my authoring training input explicitly. If that is false, proposal quality is low and nothing compounds.

**Operating principle: I review, I do not author.** Precept proposes every change; I keep it or dismiss it. I never hand-write the configuration.

## Objectives and key results

**O1.** The platform's agentic processes and output quality improve with each session, from my explicit direction and from the implicit signals in every interaction: my style, corrections, questions, and requests.
- Key result: anything I convey in a session (a correction, a preference, a way of working) becomes embedded automatically in how the platform's agents operate and stays that way, so I do not have to convey it again.
- Key result: what it embeds is what I meant, so its learnings hold up instead of being overridden.

**O2.** The knowledge the platform comes across while working compounds and stays current with each session, and is retrieved for both me and the agentic processes whenever it applies.
- Key result: any information the platform has come across before is retrieved in relevant session contexts, so it does not have to be re-learned in new sessions.
- Key result: everything the platform knows is available for me to look up.
- Key result: what surfaces is current, not stale or superseded.

## Non-goals

The goal (a platform that keeps improving how my agentic AI work gets done and the knowledge it depends on) makes several adjacent capabilities look in scope. They are not. Each line is a boundary I chose, with its reason.

1. Not a replacement for Claude Code's native memory. Precept runs alongside native memory, it does not supersede it. Native memory self-writes freeform notes with no review step and no compliance guarantee. Precept is the governed layer on top: typed entities, an explicit keep/dismiss gate, lifecycle governance (decay, supersede, conflict detection), and compilation of the invariant subset into deterministic enforcement.
2. Not autonomous. Nothing enters the catalog or takes effect without my explicit approval. Precept proposes every change; I keep it or I dismiss it.
3. Not a system that enforces everything. Most entities steer behavior; only true invariants are hard-enforced. Over-enforcement produces false blocks, and a tool that false-blocks gets turned off, which forfeits the whole capability.
4. Not a general product. This is my own setup, published, not something built for other users. There is no packaging, onboarding, or multi-user support, because generality would trade away the personalization to my workflow that is the entire point.

## Dependencies

What Precept relies on that I do not control. For each I note the consequence if it does not hold.

1. Claude Code extension contract (the largest one, and a live risk). Precept runs on my local machine as extensions to Claude Code: five hooks and a CLI wired into ~/.claude, depending on the whole extension contract (the hook lifecycle of Stop, SessionEnd, SessionStart, UserPromptSubmit, PreToolUse, the exit-code and JSON protocol, permission precedence of deny over ask over allow, settings.json, and the .claude/ file layout). Anthropic defines this contract, not me, and it has changed before. If a release alters the hook protocol or the file layout, enforcement or the learning loop can break until I update Precept.
2. Inference for the learning loop. Detection and proposal generation need model inference, selected by the PRECEPT_INFERENCE environment variable: the API-key backend (the Anthropic SDK) by default, or my Claude subscription through the local claude CLI, which my own setup pins on. The subscription quota is shared with my interactive Claude Code use, so background detection competes with my foreground work. If no backend is reachable the learning loop cannot run; by the fail-open design it degrades the loop, never blocks a session. The enforcement runtime uses no model and does not carry this dependency.

## Functional requirements

Each requirement is an observable behavior with a status and the objective it serves. Status: **built** (implemented and covered by tests), **partial** (a subset works, the rest is specified), **designed** (specified against the verified host contract, not implemented), **planned** (roadmapped, not specified). Only 3 of the 9 entity types are built; the table says so line by line, and nothing below is marked built that a reader cannot exercise from a clone.

**R1: Processes** (serves O1). The ways I work with an agent, captured as typed entities and committed to targets Claude Code reads.

| # | The system... | Status |
|---|---------------|--------|
| R1.1 | compiles every kept correction into exactly one typed entity with a defined commit target | built |
| R1.2 | supports nine entity types, each with a declared enforcement tier and commit target (table below) | 3 built, 1 partial, 5 designed |
| R1.3 | assigns each correction to an entity type from its shape (a ban, a standing convention, a procedure, a fact) | partial |
| R1.4 | scopes each entity (global, repo, language, path) and loads it only where the scope matches | built |

Entity types, their commit targets, and whether Claude Code enforces the result (HARD) or is merely steered by it (SOFT):

| Entity | Commit target | Tier | Status |
|--------|---------------|------|--------|
| Rule | hooks + `permissions.deny` | HARD | built |
| Knowledge note | local full-text index (the Data pillar) | SOFT | built |
| Convention | Precept-owned `.claude/rules/*.md` | SOFT | built |
| Skill | `.claude/skills/<name>/SKILL.md` | SOFT | designed |
| Agent persona | `.claude/agents/<name>.md` | HARD tools, SOFT prompt | designed |
| Output style | `.claude/output-styles/<name>.md` | SOFT | designed |
| Slash command | `.claude/commands` or `.claude/skills` | SOFT | designed |
| MCP / tool config | `.mcp.json` / `mcpServers` | config (not enforcement) | designed |
| Permission profile | `settings.json` `permissions` | HARD | partial |

R1.2 is the honest center of this section. Six of the nine rows are not yet real. They share one property that makes each a bounded addition rather than a new system: the same `Lesson` type, the same keep/dismiss gate, and the same writer-registry seam, differing only in the file they write. That is a claim about design leverage, not about completion, and the Status column keeps the two apart.

**R2: Data** (serves O2). The knowledge those processes act on, captured for recall and reuse.

| # | The system... | Status |
|---|---------------|--------|
| R2.1 | captures knowledge from a session and stores it in a local, rebuildable index | built |
| R2.2 | injects relevant stored knowledge into a session at prompt time, selected by relevance | built |
| R2.3 | catalogs the entities my work operates on (projects, domains, people) as typed records, not freeform notes | planned |

R2.2 is keyword-first retrieval today. Whether it needs semantic (embedding) retrieval is left open and gated on a measurement, not assumed (see Open questions).

**R3: Self-improving** (serves O1 and O2, the mechanism by which both compound). A loop that reads my sessions and proposes refinements to the processes (R1) and the data (R2) for my review.

| # | The system... | Status |
|---|---------------|--------|
| R3.1 | detects candidate entities from a session transcript, biased to abstain over a false capture | built |
| R3.2 | applies no proposal until I explicitly keep it; a dismissed proposal leaves no trace | built |
| R3.3 | keeps the catalog current through governance: decay of stale entities, supersede of replaced ones, conflict detection between contradictory ones | built |
| R3.4 | drives the review gate (catalog search, entity show, review pending, decide) from any local MCP client, not only the CLI | built |
| R3.5 | drafts candidate entities from external best practices it reads on its own, for the same review gate | planned |

R3.2 is the constraint the whole platform is built around: the system proposes, I dispose, and the proposing half (R3.1, R3.5) can be wrong cheaply because nothing it produces is live until R3.2 passes.

**R4: Enforcement** (serves O1, as a guarantee, not a headline). The subset of R1 that is a true invariant compiles to a mechanism Claude Code enforces without the model in the loop.

| # | The system... | Status |
|---|---------------|--------|
| R4.1 | compiles an invariant entity into deterministic enforcement: a hook decision, a permission rule, or a subagent tool-scope | built |
| R4.2 | for an invariant with no mechanical check, runs a model verdict at a deterministic turn-end gate (the gate fires every turn; only the verdict is a model call) | built |

R4 is a supporting capability, not an objective: it is how a proven-invariant preference is made to stick for the cases where steering is not enough. Most entities never reach R4; over-enforcement produces false blocks, and a false block gets a tool turned off.

## Non-functional requirements

These are the properties that have to hold for a system that learns from my sessions, rewrites my agent's configuration, and runs inside my coding tool to be one I can leave running unattended. Each is stated as a property with a verification method and a status (built, partial, designed, planned). The frame is ISO/IEC 25010:2023; the two attributes it does not cover well for a self-improving agent (auditability and accountability) are stated explicitly rather than folded into security.

| # | Quality | Requirement | Verified by | Status |
|---|---------|-------------|-------------|--------|
| N1 | Reliability | The runtime fails open. No error, missing key, or unreadable cache ever blocks a session; the worst outcome of a Precept fault is that enforcement does not fire, never that my session wedges. | Fault-injection tests at every hot-path seam (unreadable cache, malformed event, model error) assert an allow decision. | built |
| N2 | Performance | The enforcement hot path is stdlib-only: no model call, no network, no third-party import. It runs as a fresh process on every guarded tool call, so its cost is a bounded local computation, not a round trip. | A retrieval and enforcement perf test; the import graph of `enforce.py` is asserted to exclude the SDK and pydantic. | built |
| N3 | Safety | Model-authored logic can never harm the machine. It executes only as data through a fixed interpreter (no `eval` or `exec`); regex is ReDoS-guarded by a compile-time reject of catastrophic forms and a runtime wall-clock bound that fails to "no match"; nested inference is recursion-guarded. This is ISO 25010:2023 fail-safe: the failure of a model-generated artifact degrades to inert, not dangerous. | Adversarial tests: a catastrophic pattern is rejected at compile and abandoned under bound at runtime; a fork-bomb-class correction cannot compile to executable code. | built |
| N4 | Security | The enforcement plane sends nothing off the machine and holds no credential; the learning plane's model access is the only egress and is disabled by one environment variable. Local-first is the default, not a setting. | The hot path has no network import (shared with N2); a test asserts the learning loop is inert when the disable flag is set. | built |
| N5 | Integrity | An entity cannot claim enforcement it cannot deliver. The HARD/SOFT boundary is validated in the type system: a HARD tier on an event that physically cannot block a call is a construction-time error, not a runtime surprise. A correction earns determinism only by compiling to a matcher that passes a typed validator; otherwise it stays soft. | A type-level test asserts HARD on a non-blockable event raises; a compile-fidelity check is the next eval milestone (see KPIs). | built (boundary), partial (fidelity) |
| N6 | Auditability | Every enforced decision and every learned entity is traceable to its origin. `precept why` shows where a lesson came from and why it is trusted (the provenance gate: user-typed turns only); each policy match writes an append-only decision-log line; the verdict prompt for a judgment rule is stored on the entity's own card. Nothing enforces anonymously. | Tests assert a match appends a well-formed log line and that `why` resolves provenance; the log is the source of the live fire counts governance reads. | built |
| N7 | Accountability | No configuration change and no catalog entry takes effect without my explicit keep. Detection is abstain-biased and fails closed (a missed lesson beats a false one); governance (decay, supersede, conflict) only ever proposes, and a retired rule is archived with a back-pointer, never hard-deleted. The system has no autonomous write path to my agent's behavior. | The review gate is exercised in tests (keep activates, nothing enforces before it); governance tests assert propose-only and recoverable archive. | built |
| N8 | Reversibility | All writes to ~/.claude are atomic (temp-in-same-dir, fsync, rename) and exactly inverse on uninstall, so adopting Precept is a decision I can fully undo. Every commit target is backed up before it is touched. | Install and uninstall round-trip tests assert the tree returns to its pre-install state byte-for-byte. | built |
| N9 | Testability | The model client is injectable at every AI seam, so the entire suite (292 tests) runs offline and hermetic, with no key and no network. Non-determinism is confined to the seams a fake client replaces. | CI runs the full suite with no `ANTHROPIC_API_KEY` and no network; a fake client is the default in tests. | built |
| N10 | Privacy boundary | Learned content (the catalog, local state, any vault) lives outside this repository, and the boundary is enforced, not asserted: a CI test fails the build if a populated catalog card, local session config, or personal marker (home paths, phone patterns, vault mounts) is ever tracked. The public code plane never contains my private data plane. | `tests/test_repo_privacy.py` runs in CI and fails on any tracked private artifact. | built |

A note on what is deliberately absent. There is no availability SLA, no horizontal-scalability target, and no multi-tenant isolation requirement, because there is one user on one machine and the system is allowed to be absent (it fails open by design, N1). Adding those would be answering a question nobody asked. The one attribute I would add before any other user touched this is a catalog schema-version and migration guarantee: today the reversibility guarantee (N8) covers a clean uninstall but not forward-migration of a catalog that has accumulated for months if the card format changes. I name it here as a known gap rather than imply it is handled.

## KPIs

The key results above are deliberately qualitative. This is where the numbers live. A KPI here is one of two things: a standing dial I watch continuously to keep the system healthy, or the single number behind a key result. KPIs are not a restatement of the key results. A key result is the outcome I want (a correction stops recurring); the KPI is the metric and threshold that says whether it happened (recurrence rate, target near zero).

I mark each KPI as live (instrumented and reporting today) or instrumented, not yet live (the harness exists, the wiring is a named next milestone). Where I have not set a target threshold yet, I say so and point to the open question that has to close first. I would rather leave a threshold blank than invent one to look finished.

### Standing dials (live today)

These run continuously and do not depend on a model call, so they are the numbers I am willing to state flatly.

**Enforcement scorecard.** I run the real enforcement engine, unchanged, over a committed golden set of 25 cases and tally the result as a confusion matrix. No model is called, so there is no eval noise here, and the check is gated in CI. Current run: 10 true positives, 0 false negatives, 0 false positives, 15 true negatives. That is 100% recall (10 of 10) and a 0% false-block rate (0 of 15). I state the claim as narrowly as the test earns it: of the violations Precept has a compiled rule for, it blocks every one and blocks no compliant call. It says nothing about violations it has no rule for yet. Recall is the metric I am pushing; the false-block rate is the guardrail I am protecting, because a false block is the expensive error (it interrupts real work), which is also why enforcement is biased to allow at runtime.

**Learning-loop token cost.** I meter the tokens spent by the loop's model-calling flows (detect, compile, and the verdict calls) so the cost of self-improvement is visible and can be throttled. This dial exists because the loop runs on my Claude Code subscription quota, so a detect call on every stop competes with my own interactive use. Tokens are the native unit; a dollar figure is a notional weight at API rates, not a bill. There is no target threshold here on purpose: this is a watch-and-throttle dial, not a goal to optimize toward.

### The number behind each key result

Each key result has exactly one KPI. Several thresholds are not set yet, and I name the reason for each rather than fill it in.

| Objective | Key result (qualitative) | KPI (the number) | Target | Status |
|---|---|---|---|---|
| O1 | Conveyed once, stays embedded | Recurrence rate of a correction I already conveyed | Near zero | Instrumented, not yet live |
| O1 | Learnings hold up, not overridden | Rate at which embedded learnings are later overridden or rolled back | Low; threshold not yet set | Instrumented, not yet live |
| O2 | Retrieved when relevant | Retrieval recall at k in relevant contexts | Threshold not yet set | Instrumented, not yet live |
| O2 | Available to look up | Share of the catalog searchable and readable by me | High | Live |
| O2 | Current, not stale | Stale-recall rate (share of surfaced knowledge that is out of date or superseded) | Low | Instrumented, not yet live |

Notes on the unset thresholds, so the blanks are honest and not lazy:

- Override and rollback rate (O1): I know the direction (low) but not the acceptable floor, because I do not yet have enough embedded learnings with enough session history to know what a normal, healthy override rate looks like. Setting a number before I have that baseline would be guessing.
- Retrieval recall at k (O2): the threshold is tied to the open question of whether structural, keyword-overlap retrieval is good enough or whether the fuzzy subset needs a semantic (vector) layer. Recall at k is exactly the measurement that decides that question, so I will not pin the target until the measurement is running and has told me which regime I am in.

### Recurrence rate is the metric I trust most, and I still cannot quote it yet

Recurrence rate is the closest thing Precept has to a north-star KPI: if a correction I made once comes back, the core promise (things compound instead of resetting) has failed, independent of how any individual artifact was built. It is a leading indicator, it needs no model call to compute, and it maps directly to the goal. It is instrumented but not yet live, so I am not quoting a value. Reporting a made-up recurrence number would defeat the exact honesty this section is meant to demonstrate.

### The honest gap: whether enforcement actually improves adherence

The scorecard above proves the enforcement engine is correct on its golden set. It does not prove that turning enforcement on makes my agentic work measurably better. That is a different and harder claim, and it is the one I most want to be careful about.

Whether enforcement improves adherence (O1) is a paired before and after measurement: run a representative workload with enforcement off, run it with enforcement on, and compare adherence. I report that delta with a 95% confidence interval, and I do it this way for a specific reason. Agentic-eval infrastructure is noisy: identical runs of the same evaluation routinely shift by several points, and published work puts run-to-run swings in the 8 to 14% range, with roughly a one-in-seven chance that a pairwise comparison flips direction on a re-run (Scale AI; recent arXiv work on measuring evaluation noise). A single before-and-after pair that shows, say, a four-point gain is inside that noise band and proves nothing. So the only defensible way to report this is a distribution over repeated paired runs with an interval, and a claim of improvement only when the interval clears the noise floor.

The reporting harness is built. Live wiring is the next milestone. Until then, the honest status is: I can prove the enforcement engine does what it says on a fixed set of cases, and I cannot yet prove it moves the outcome I actually care about. I would rather state that plainly than show a single green number that the noise literature says I should not believe.

## Roadmap

I order this by dependency and priority, not by date. The rule I am following: harden the loop that already exists before I widen it. The core learning loop is built; the next phase proves it works and measures what it costs; only then do I add more entity types, a data catalog, and autonomous learning on top of a foundation I trust.

Each phase below is defined by an outcome, not a ticket list. Confidence is highest for Now and decreases across Next and Later; Later is directional and will reorder as my real usage tells me which corrections matter most.

### Now (built)

Outcome: the core loop runs end to end, and its one measurable guarantee is enforced in CI.

- The full loop is working: detect a candidate correction from a session, review it, keep it, then either enforce it deterministically or steer the agent with it.
- 3 of the 9 planned entity types are implemented: Rule, Knowledge note, and Convention. The other 6 are not built.
- The deterministic enforcement eval is wired and CI-gated, so a kept correction that should be enforced cannot silently regress.
- 292 offline hermetic tests, plus ReDoS and recursion guards on the matcher path.

This is the smallest version of Objective O1 (direction improving across sessions) that actually holds together. It is real, but it is narrow: it improves behavior only for the correction types the three built entity types cover, and the only property proven automatically today is that enforcement fires.

### Next (in progress)

Outcome: I can measure that the loop actually changes behavior, trust that what it generates matches the correction it came from, and know what the learning flows cost.

Everything in Next hardens the loop that already exists. Nothing here widens scope; that is deliberate.

- Paired before-and-after enforcement eval, live. This is the direct measurement of O1: run the same session with and without a kept correction and show the behavior changed. Today enforcement is proven to fire; this proves it helps.
- Compile-fidelity eval. When a correction is compiled into a matcher, does that matcher actually capture the correction it came from, and not something broader or narrower? This closes the gap between "I kept a correction" and "the system learned the right thing."
- Token cost report for the learning-loop flows. A system that runs on every session has to justify its own overhead. I want the cost of detection, review, and compilation visible before I add more flows on top.

Why these come before anything in Later: the before-and-after eval and the compile-fidelity eval turn the loop's two unproven assumptions (that enforcement improves behavior, and that compilation is faithful) into measured properties. Widening to more entity types or adding autonomous learning before those checks exist would scale an unverified mechanism. I would rather scale a measured one.

### Later (planned, not built)

Outcome: the system compounds knowledge as well as direction (Objective O2), proposes its own improvements under the same review gate, and covers the correction types I actually hit.

These are directional. I am naming them honestly as not built, and the order within Later will follow evidence from my real usage, not this list.

- Typed data catalog. The projects, domains, and people my work operates on, as first-class typed entities. This is the backbone for O2 (knowledge that compounds and is retrieved when it applies) and it does not exist yet.
- Background learning. The system drafts improvement proposals from external best practices on its own, gated by the exact same human review that governs corrections today. Autonomy is deferred on purpose: I only want the system proposing changes once the review gate and the fidelity checks it depends on are proven.
- The remaining entity types. The other 6 of 9, added in the order the correction types show up most in my real usage, so I build coverage where it pays off rather than for completeness.

The through-line: Now is a working loop, Next makes it measured and affordable, Later makes it broad and partly self-driving. I widen scope only after the foundation under it is one I have verified, not one I am hoping holds.

## Open questions

These are unresolved design decisions, not planned work. Each names the choice, the options, and the specific evidence or gate that would settle it. Until then, the shipped default is stated first.

1. Semantic recall: does this corpus actually need embeddings? Default today is keyword retrieval (FTS/BM25). The risk is that keyword search misses fuzzy or paraphrased knowledge that never shares a literal term with the query. The alternative is an embedding index, at the cost of another index to build, store, and keep in sync. I will add embeddings only if a Recall@k eval on my own corpus shows keyword search missing relevant entities. The threshold that counts as "missing" is not yet set, so the eval cannot yet return a verdict.
2. Router precision: at what confidence does the router auto-route versus ask me? When a correction is ambiguous across homes (rule vs convention vs skill), auto-routing everything risks silent misfiling; asking on everything defeats a self-improving system. The open decision is where to set that confidence gate, and whether one gate suffices or each destination needs its own. Resolved by measuring routing accuracy against my keep and dismiss decisions.
3. Background-learning trust: is the review gate sufficient at volume? When Precept reads external best practices and proposes entities, every proposal passes my review, so nothing enters unreviewed. The open question is whether that holds at volume: many proposals can each pass review yet still degrade the catalog through redundancy or drift. The decision is what constraint sits alongside per-item review (a proposal budget, a dedup or novelty check, a staging area).
4. Coverage: how do I measure the misses, not just the hits? Today I can measure the accuracy of corrections that became entities. I cannot yet measure the ones that should have and did not, the more dangerous error, because a silent miss leaves no artifact. The decision is how to estimate that miss rate: sampling raw sessions for corrections and checking capture, or holding out a labeled set.

## Related documents

This README is the product spec and the entry point, kept deliberately high level. The documents below are the deeper design and decision records. Each is the single source of truth for its topic, so this spec points to it rather than restating it.

- [ARCHITECTURE.md](ARCHITECTURE.md): the module map and the data flow between parts. Go here first to see how Precept fits together and to place any component this spec mentions.
- [docs/ARTIFACTS.md](docs/ARTIFACTS.md): the per-entity specification and status tracker for the nine entity types. Go here for what each entity is, its schema, and whether it is built, in progress, or planned.
- [DECISIONS.md](DECISIONS.md): the load-bearing engineering decisions and their reasons. Go here to understand why the system is built the way it is before proposing a change.
- [docs/ANTHROPIC-CONFORMANCE.md](docs/ANTHROPIC-CONFORMANCE.md): a self-audit against Anthropic's published agent-rules and memory guidance, including the one open retrieval gap.

## Install

```bash
git clone https://github.com/NoaBarzelay/precept && cd precept
uv venv && uv pip install -e ".[dev]"
pytest -q            # 292 tests, offline and hermetic

precept install                 # wire hooks into ~/.claude (idempotent, atomic, backed up)
precept bootstrap               # seed candidate entities from an existing setup
precept detect <transcript>     # classify a session into a candidate entity
precept list                    # show the catalog
precept why <id>                # the review gate: where a lesson came from and why it is trusted
precept keep <id>               # the review gate: keep -> active
precept evals                   # the deterministic scorecard
precept doctor                  # resolved paths, sync-safety check, hook reachability
precept mcp                     # stdio MCP server over the catalog + review gate (needs precept[mcp])
```

## License

MIT.
