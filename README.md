# Precept

## Context

Coding agents are by default mostly stateless: they do not retain information beyond their context window, and learnings do not transfer from session to session. Without a layer that compiles how you work and a layer that stores what you know, the effort does not compound across sessions. Precept is the process and data layer I built so both compound across sessions.

## Goal

A personal platform that, on its own, learns and keeps improving both how I want my agentic AI work done and the knowledge my work depends on, so the two compound across sessions instead of resetting each time.

## Objectives and Key Results

**O1.** The platform's agentic processes and output quality improve with each session, from my explicit direction and from the implicit signals in every interaction: my style, corrections, questions, and requests.
- **Key result:** anything I convey in a session (a correction, a preference, a way of working) becomes embedded automatically in how the platform's agents operate and stays that way, so I do not have to convey it again.
- **Key result:** what it embeds is what I meant, so its learnings hold up instead of being overridden.

**O2.** The knowledge the platform comes across while working compounds and stays current with each session, and is retrieved for both me and the agentic processes whenever it applies.
- **Key result:** any information the platform has come across before is retrieved in relevant session contexts, so it does not have to be re-learned in new sessions.
- **Key result:** what surfaces is current, not stale or superseded.

## User Stories

As an engineer who runs most of my work through coding agents:

- I want to stop re-teaching the agent things I have already told it, so that my time goes to the task instead of to repeating myself.
- I want the standards I care about to actually hold in the agent's work, so that I can trust its output instead of re-checking for mistakes I have already flagged.
- I want the agent to know the facts my work depends on, my stack, my conventions, my projects, so that I do not re-explain my setup every session.
- I want the knowledge my work has built up to be available to me and to my agentic processes when it is relevant, so that I build on what I have already established instead of working from memory.
- I want to stay in control of how my agents behave, so that my setup does not drift or change without me.
- I want the agent to reflect how I work now, so that habits I have moved past stop showing up.

## Non-Goals

The goal (a platform that keeps improving how my agentic AI work gets done and the knowledge it depends on) makes several adjacent capabilities seem potentially in scope. Each line is a boundary I chose, with its reason.

1. **Not a replacement for Claude Code's native memory.** Native memory is Claude Code's built-in recall: the CLAUDE.md files I write plus auto memory, where Claude self-writes freeform notes into context each session. It captures freely but leaves what it captures as unmanaged context, with no review, structure, upkeep, or ability to enforce. Precept is the governed layer over that same knowledge: reviewed before it enters, structured, kept current, and for the invariant subset, enforced.
   - *Why:* they are different layers. Native memory captures and recalls; Precept governs what is kept and enforces the invariant subset, so it builds on native memory rather than duplicating it.
2. **Not hard enforcement of every rule it learns.** Most conventions Precept learns are injected as context that steers behavior (soft); only true invariants compile into a deterministic block (hard).
   - *Why:* I keep the hard set small on purpose, because over-enforcement produces false blocks, and a tool that false-blocks gets turned off, forfeiting the capability.
3. **Not model training or fine-tuning.** Self-improvement in the context of Precept means the knowledge base and enforcement layer on top of the model improve over time, not the model's weights.
   - *Why:* Precept runs on Claude through Claude Code; training would mean self-hosting an open-weights model and trading away frontier capability. Precept is also cheaper and reversible, versus the baked-into-weights option.
4. **Not model- or tool-agnostic.** Precept is built on Claude Code specifically: its hooks, its CLAUDE.md contract, its permission model. Portability to other agents is out of scope.
   - *Why:* Precept enforces and injects context through Claude Code's hook, permission, and memory contracts, which have no cross-agent equivalent; a portable version would fall back to a lowest common denominator that cannot enforce.
5. **Not productized for distribution.** This is my own setup, published as-is: no packaging, onboarding, or multi-user support. It is public to be read and copied from, a reference to borrow, not a product to install.
   - *Why:* offering it as a product means owning packaging, support, and a roadmap shaped by other users' needs, which would pull it away from my own workflow; publishing the source lets anyone copy what they want without that.

## Risks and Mitigations

A pre-mortem: assuming Precept had failed a year into daily use, these are the causes, ordered by impact, each paired with its mitigation. Undecided design forks live in Open Questions.

1. **The learning signal is missed or misinterpreted** (impact: high, probability: medium). Precept's base assumption is that ordinary session activity is a rich enough signal that can be correctly accurately be interpreted by an LLM. It can fail by (1) missing a real preference when the signal is implicit (e.g., text edits) (2) capturing the wrong intent behind a change (3) flattening a conditional preference (do X, except in case Y) into a blanket rule that drops the exception, so the rule over-fires.
   Example: I revert the agent's switch from `requests` to `httpx` because I wanted it in its own PR, and it records "do not use httpx" as a standing preference I never held.

   *Mitigations:*
   - **In-session approval:** I approve each inferred preference at the moment it is discovered. [R3.2]
   - **Preference origin is documented:** the excerpt of the sessions that yielded the preference is documented word-to-word so it can be judged. [N6]
   - **Contradiction check:** a new preference is checked against my existing rules, and any conflict is surfaced for me to reconcile before it takes effect. [R3.3]
   - **Stated condition:** every new preference must state the condition it holds under, even when the answer is "always holds," so the model always reasons about potential exception when defining preferences. [R1.4]
   - **Accuracy on weak signals:** weak signals are documented, not dropped, and if resurfaced across sessions are promoted to actual preference. [R3.1]
   - **Intent inferred through broad context:** intent is interpreted using the surrounding turns, not a lone action/prompt. [R3.1]
   - **Self-correction:** when I correct an inferred preference at the gate, Precept keeps the delta between what it inferred and what I committed and folds it back into how it infers, so that class of mistake stops recurring: a similar correction becomes an example for the next inference, a correction I repeat becomes a standing rule on the inference step itself, and my keep and dismiss record calibrates its scope. [R3.6]
   - **Hindsight audits:** on a schedule, a random sample of past sessions is re-reviewed with a stronger, lower-threshold pass to catch preferences the live detector missed, recover them, and calibrate the preference detection mechanism. [R3.7]

2. **Mis-enforcement: unwanted behaviors are enforced** (impact: high, probability: medium). A recorded preference can be enforced incorrectly when (1) the enforcement is based on LLM reasoning, which can miss or misinterpret parts of the requirements (2) a preference becomes irrelevant but continues to be silently enforced (3) a preference is inaccurately defined (too blunt / wrongly scoped etc). Mis-enforcement is time and quality consuming, erodes the trust in enforcement and pushes to override or switch it off.
   Example: a rule I set in a shared repo to block direct commits to `main` is applied too broadly and fires in a solo scratch repo, where committing straight to `main` is exactly what I want, blocking every commit until I notice why.

   *Mitigations:*
   - **Prefer a deterministic check:** a model verdict is used only when the requirement cannot be checked mechanically, so most enforcement never runs LLM reasoning and that failure cannot arise there. [R4.1, R4.2]
   - **Fail toward not-enforcing:** a low-confidence or errored verdict defaults to allowing, because a wrong enforcement is the costly error, so an unreliable read degrades to no enforcement rather than a wrong one. [N1]
   - **Judge the whole requirement:** when a verdict is used it runs against the full recorded requirement and the turn's context, not a fragment, so it is not set up to miss a part. [R4.2]
   - **Deliberate authoring:** I approve each rule before it can enforce, with its scope and strength shown, so a blunt, mis-scoped, or over-strong rule is refined or rejected at the gate. [R3.2]
   - **Confirmed in practice before it goes live:** the first times a newly recorded rule would enforce, it tells me what it is about to do and why and asks whether that is what I intended; a no refines the rule, and after three consecutive yeses it becomes fully operational and stops asking. [R4.3]
   - **Validity bound to an observable justification:** a rule's stated condition doubles as its justification, and when that condition is observable (the project uses uv, we are on the release branch, this config exists) the system checks it and retires or flags the rule when it no longer holds, so the rule expires with the situation that created it rather than on a guess. [R1.4, R3.3]
   - **Contradiction triggers reconsideration:** a conflict, an override of the rule or activity that runs counter to it, flags the rule for re-confirmation. [R3.6, R3.3]
   - **One-command override:** I can disable the offending rule immediately, and undoing it is exact. [N8]
   - **Auditable, diagnosable, and self-correcting:** every enforcement records what it did and why, so a wrong one names its rule and its basis (which is what makes override possible) and, once I correct it, feeds back so the same mistake does not recur. [N6, R3.6]

3. **A defined convention fails to be enforced** (impact: medium, probability: high). A learned behavior can be unenforced if it is (1) not retrieved in the relevant context (2) ignored: it is retrieved but overlooked under long or conflicting context.
   Example: in `acme-api` I keep the convention "every endpoint returns through the `envelope()` helper so all responses share one shape." Deep into a long session adding a reporting feature (several new files, many tool calls), the model writes the fourth endpoint and returns a raw dict, skipping `envelope()`, even though the convention is retrieved and sitting in its context: a single standing line loses out to the immediate goal, it was loaded near the top where recall is now weakest, and adherence to any one instruction falls as the context grows.

   *Mitigations:*
   - **Store each preference in the type whose load rule fits it:** a path-scoped rule (loads on the files it governs), a described skill (loads when the task matches its description), or the small always-on core (a few globals), so it enters context when relevant by that type's own mechanism. [R1.3, R1.4]
   - **Author it for adherence:** specific, concise, non-conflicting, and named for how it is matched (correct path globs, or a trigger-rich description), because vague or conflicting instructions are followed arbitrarily. [R1.4, R3.3]
   - **Bounded always-on core:** the always-loaded set is capped and everything else is scoped, since adherence drops as that set grows past a couple hundred lines. [R1.4, R1.5]
   - **Enforce or verify the must-hold few:** a preference that must hold regardless of attention is moved off context into a hook or checked at task end, because context alone cannot guarantee compliance. [R4.1, R4.2]

4. **Behaviors and information become hard to track and use as they accumulate** (impact: medium, probability: high). As the information retained in catalog through sessions and the enforced behaviors keep compounding, usability and recall can degrade due to problems such as keyword retrieval degrading at scale, retrieval precision falling as the index grows so more loosely matching entries crowd the top-k and the truly relevant one drops below the cutoff, too much being injected at once so that even a retrieved entry loses attention (a model's adherence to any single instruction weakens as the number of instructions in context rises, and long-context recall is uneven, with material in the middle of a large context the most likely to be passed over), and accumulated entries starting to contradict one another so the model resolves the conflict arbitrarily. Where risk 3 is one convention losing out within a single session, this is the corpus as a whole decaying as it accumulates, which makes that failure steadily more frequent and harder to diagnose.
   Example: after months of use the catalog holds a few hundred entries, and many share generic terms like `test`, `error`, or `client`. I start an endpoint that shapes error responses, and the one convention I need, "errors return through the `problem()` helper as RFC-7807", ranks below the retrieval cutoff: a dozen other entries also match on `error` and fill the top-k ahead of it, so it is never injected. On the turns where it does clear the cutoff, it lands in the middle of a long block of retrieved rules, the position a model is least likely to act on, and the agent writes a raw error dict as if the convention were not there.

   *Mitigations:*
   - **Governance lifecycle:** decay retires an entry once its stated condition no longer holds, supersede folds a newer entry over the one it replaces, and conflict detection surfaces contradictory entries for me to reconcile, so the catalog is actively curated rather than only appended to. [R3.3]
   - **Budgeted always-on core:** the always-loaded set is capped and everything else is scoped so it loads only when its condition matches, a path-scoped rule when a file under its globs is touched, a language- or repo-scoped one only inside that language or repo, and a skill only when the task fits its description; most of the catalog therefore stays out of context, and accumulation cannot silently push standing context past the range where adherence holds. [R1.4, R1.5]
   - **Merge on capture, not only cleanup after (not yet built):** governance above prunes duplicates once they exist; the root fix is to avoid minting them. A candidate that matches an existing entry above a similarity threshold would update that entry instead of creating a parallel one, so the catalog trends toward one entry per preference rather than a drift of near-copies to reconcile later. [would extend R3.3]
   - **A budget on the retrieved slice, not just the always-on set (not yet built):** the cap above bounds standing globals, but the just-in-time retrieval path can still inject a long, low-precision list as the index grows. Capping how many entries are injected per turn and requiring a minimum relevance score would drop weak near-matches rather than padding context with them, keeping injection inside the range where the model still attends to each entry. [would extend R2.2]
   - **Rank by precision signals, not lexical overlap alone (not yet built):** at scale, keyword score cannot separate the one relevant rule from many generic near-matches. Combining it with scope-specificity (a rule scoped to this exact path or repo outranks a global one), recency, and how many times the rule has been confirmed would lift the precise, live entry back above stale generic ones and into the top-k; an embedding index is one option here, taken only if a Recall@k eval on my own corpus shows keyword search missing relevant entries. [would extend R2.2; Open Question 1]
   - **Periodic consolidation of the catalog (not yet built):** beyond retiring entries one at a time, a scheduled compaction would merge clusters of overlapping conventions into a single canonical entry, so total count grows sublinearly with corrections instead of linearly, holding both retrieval precision and injection volume down at the source. [would extend R3.3]
5. **The Claude Code contract changes underneath Precept** (impact: medium, probability: medium). Precept rides Anthropic's hook, exit-code, and permission surface, which is unversioned and has changed before; because the runtime fails open (N1), a change can silently downgrade a HARD rule to a no-op, so the real danger is not the fix (localized and small) but not noticing enforcement stopped. *Mitigation:* a startup and version-triggered self-check that asserts a known-bad action is still actually blocked and surfaces a failure loudly, so a break is caught and fixed quickly rather than running silent.
6. **The system becomes too expensive or too slow** (impact: medium, probability: medium). The loop's model calls cost money on the API backend and burn shared subscription quota on the CLI backend, and a Stop-gate verdict runs synchronously in the turn; too slow or costly and I stop running it, which halts the compounding. *Mitigation:* the enforcement hot path is model-free (N2), verdicts are consolidated to one relevance-gated call per turn, Haiku serves the cheap paths and Sonnet only compile, and a token meter prices per-flow spend; designed, detection moved fully async off the interactive path.
## Functional Requirements

Each requirement is an observable behavior with a status. Status: **built** (implemented and covered by tests), **partial** (a subset works, the rest is specified), **designed** (specified against the verified host contract, not implemented), **planned** (roadmapped, not specified). Only 3 of the 9 entity types are built; the table says so line by line, and nothing below is marked built that a reader cannot exercise from a clone.

**R1: Processes.** The ways I work with an agent, captured as typed entities and committed to targets Claude Code reads.

| # | The system... | Status |
|---|---------------|--------|
| R1.1 | compiles every kept correction into exactly one typed entity with a defined commit target | built |
| R1.2 | supports nine entity types, each with a declared enforcement tier and commit target (table below) | 3 built, 1 partial, 5 designed |
| R1.3 | assigns each correction to an entity type from its shape (a ban, a standing convention, a procedure, a fact) | partial |
| R1.4 | scopes each entity (global, repo, language, path) and loads it only where the scope matches | built |
| R1.5 | caps the always-loaded set of entities at a size budget and loads the rest only in scope, so standing context stays within the range where adherence holds | designed |

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

**R2: Data.** The knowledge those processes act on, captured for recall and reuse.

| # | The system... | Status |
|---|---------------|--------|
| R2.1 | captures knowledge from a session and stores it in a local, rebuildable index | built |
| R2.2 | injects relevant stored knowledge into a session at prompt time, selected by relevance | built |
| R2.3 | catalogs the entities my work operates on (projects, domains, people) as typed records, not freeform notes | planned |

R2.2 is keyword-first retrieval today. Whether it needs semantic (embedding) retrieval is left open and gated on a measurement, not assumed (see Open Questions).

**R3: Self-improving.** A loop that reads my sessions and proposes refinements to the processes (R1) and the data (R2) for my review.

| # | The system... | Status |
|---|---------------|--------|
| R3.1 | detects candidate entities from a session transcript, biased to abstain over a false capture | built |
| R3.2 | applies no proposal until I explicitly keep it; a dismissed proposal leaves no trace | built |
| R3.3 | keeps the catalog current through governance: decay of stale entities, supersede of replaced ones, conflict detection between contradictory ones | built |
| R3.4 | drives the review gate (catalog search, entity show, review pending, decide) from any local MCP client, not only the CLI | built |
| R3.5 | drafts candidate entities from external best practices it reads on its own, for the same review gate | planned |
| R3.6 | learns from my corrections to its own inferences and folds them back, so the same class of mistake stops recurring | planned |
| R3.7 | periodically re-reviews a random sample of past sessions with a stronger pass, to recover preferences the live detector missed and calibrate detection | planned |

R3.2 is the constraint the whole platform is built around: the system proposes, I dispose, and the proposing half (R3.1, R3.5) can be wrong cheaply because nothing it produces is live until R3.2 passes.

**R4: Enforcement.** The subset of R1 that is a true invariant compiles to a mechanism Claude Code enforces without the model in the loop.

| # | The system... | Status |
|---|---------------|--------|
| R4.1 | compiles an invariant entity into deterministic enforcement: a hook decision, a permission rule, or a subagent tool-scope | built |
| R4.2 | for an invariant with no mechanical check, runs a model verdict at a deterministic turn-end gate (the gate fires every turn; only the verdict is a model call) | built |
| R4.3 | a newly recorded rule confirms itself in practice: on its first encounters it explains what it would enforce and why and asks whether that was intended, refining on a no and graduating to silent enforcement after three consecutive confirmations | planned |

R4 is a supporting capability, not an objective: it is how a proven-invariant preference is made to stick for the cases where steering is not enough. Most entities never reach R4; over-enforcement produces false blocks, and a false block gets a tool turned off.

## Non-Functional Requirements

These are the properties that have to hold for a system that learns from my sessions, rewrites my agent's configuration, and runs inside my coding tool to be one I can leave running unattended. Each is stated as a property with a verification method and a status (built, partial, designed, planned). The frame is ISO/IEC 25010:2023; the two attributes it does not cover well for a self-improving agent (auditability and accountability) are stated explicitly rather than folded into security.

| # | Quality | Requirement | Verified by | Status |
|---|---------|-------------|-------------|--------|
| N1 | Reliability | The runtime fails open. No error, missing key, or unreadable cache ever blocks a session; the worst outcome of a Precept fault is that enforcement does not fire, never that my session wedges. Failing open has one downside worth catching: it can let the learning loop go silently inert (an expired credential once left it dead for weeks), so each learning flow records when it cannot reach a model and a diagnostic reports an unreachable backend, surfacing a dead backend instead of letting it pass for a quiet session. | Fault-injection tests at every hot-path seam (unreadable cache, malformed event, model error) assert an allow decision; a test asserts a flow that cannot reach a model records the failure while still failing open. | built |
| N2 | Performance | The enforcement hot path is stdlib-only: no model call, no network, no third-party import. It runs as a fresh process on every guarded tool call, so its cost is a bounded local computation, not a round trip. | A retrieval and enforcement perf test; the import graph of `enforce.py` is asserted to exclude the SDK and pydantic. | built |
| N3 | Safety | Model-authored logic can never harm the machine. It executes only as data through a fixed interpreter (no `eval` or `exec`); regex is ReDoS-guarded by a compile-time reject of catastrophic forms and a runtime wall-clock bound that fails to "no match"; nested inference is recursion-guarded. This is ISO 25010:2023 fail-safe: the failure of a model-generated artifact degrades to inert, not dangerous. | Adversarial tests: a catastrophic pattern is rejected at compile and abandoned under bound at runtime; a fork-bomb-class correction cannot compile to executable code. | built |
| N4 | Security | The enforcement plane sends nothing off the machine and holds no credential; the learning plane's model access is the only egress and is disabled by one environment variable. Local-first is the default, not a setting. | The hot path has no network import (shared with N2); a test asserts the learning loop is inert when the disable flag is set. | built |
| N5 | Integrity | An entity cannot claim enforcement it cannot deliver. The HARD/SOFT boundary is validated in the type system: a HARD tier on an event that physically cannot block a call is a construction-time error, not a runtime surprise. A correction earns determinism only by compiling to a matcher that passes a typed validator; otherwise it stays soft. | A type-level test asserts HARD on a non-blockable event raises. | built |
| N6 | Auditability | Every enforced decision and every learned entity is traceable to its origin. `precept why` shows where a lesson came from and why it is trusted (the provenance gate: user-typed turns only); each policy match writes an append-only decision-log line; the verdict prompt for a judgment rule is stored on the entity's own card. Nothing enforces anonymously. | Tests assert a match appends a well-formed log line and that `why` resolves provenance; the log is the source of the live fire counts governance reads. | built |
| N7 | Accountability | No configuration change and no catalog entry takes effect without my explicit keep. Detection is abstain-biased and fails closed (a missed lesson beats a false one); governance (decay, supersede, conflict) only ever proposes, and a retired rule is archived with a back-pointer, never hard-deleted. The system has no autonomous write path to my agent's behavior. | The review gate is exercised in tests (keep activates, nothing enforces before it); governance tests assert propose-only and recoverable archive. | built |
| N8 | Reversibility | All writes to ~/.claude are atomic (temp-in-same-dir, fsync, rename) and exactly inverse on uninstall, so adopting Precept is a decision I can fully undo. Every commit target is backed up before it is touched. | Install and uninstall round-trip tests assert the tree returns to its pre-install state byte-for-byte. | built |
| N9 | Testability | The model client is injectable at every AI seam, so the entire suite runs offline and hermetic, with no key and no network. Non-determinism is confined to the seams a fake client replaces. | CI runs the full suite with no `ANTHROPIC_API_KEY` and no network; a fake client is the default in tests. | built |
| N10 | Privacy boundary | Learned content (the catalog, local state, any vault) lives outside this repository, and the boundary is enforced, not asserted: a CI test fails the build if a populated catalog card, local session config, or personal marker (home paths, phone patterns, vault mounts) is ever tracked. The public code plane never contains my private data plane. | `tests/test_repo_privacy.py` runs in CI and fails on any tracked private artifact. | built |

A note on what is deliberately absent. There is no availability SLA, no horizontal-scalability target, and no multi-tenant isolation requirement, because there is one user on one machine and the system is allowed to be absent (it fails open by design, N1). Adding those would be answering a question nobody asked. The one attribute I would add before any other user touched this is a catalog schema-version and migration guarantee: today the reversibility guarantee (N8) covers a clean uninstall but not forward-migration of a catalog that has accumulated for months if the card format changes. I name it here as a known gap rather than imply it is handled.

## Usage Examples

Four representative sessions. Each shows a preference or a fact entering through ordinary conversation, passing my review, and then changing a later session. The tag on each names the objective it serves and, for a process, its enforcement tier. Between them they span both objectives (O1 processes, O2 knowledge) and both tiers (a hard block and soft steering).

**1. A correction becomes a hard block.**
*Serves O1 (process) · HARD enforcement · R3.2, R4.1*

Session 1 · acme-api · learning

```
You     the deploy failed, install httpx and retry
Claude  $ pip install httpx
You     no, this is a uv project. use `uv pip install`, never plain pip here
Claude  Reran it as `uv pip install httpx`. Done.
        [Precept] Drafted a rule from that correction (pending, not enforced yet):
          use-uv-not-pip: in a uv project use `uv pip install`, never pip.
          Keep it, or skip?
You     keep it
Claude  $ precept keep use-uv-not-pip
        Kept -> HARD (enforced). Recompiled 7 active policies.
```

Session 2 · acme-api · three days later, a fresh session

```
You     add the stripe sdk
Claude  $ pip install stripe
        [Precept] PreToolUse blocked: use `uv pip install` here
                  (kept from your correction, session acme-0714).
        $ uv pip install stripe
        Added stripe to pyproject.toml.
```

*Payoff:* the mistake I corrected once is stopped at the tool call in a new session, without me watching for it.

**2. A style correction becomes a steering convention.**
*Serves O1 (process) · SOFT, steered not blocked · R3.2, R1.4*

Session 1 · acme-api · learning

```
You     review the new /orders endpoint before I merge
Claude  It returns a raw dict:  return {"id": o.id, "status": o.status}
You     we always return through the `envelope()` helper so every response
        has one shape. fix it, and remember it
Claude  Changed it to:  return envelope({"id": o.id, "status": o.status})
        [Precept] Drafted a convention (soft: it steers me, it does not block):
          envelope-responses: return API responses through `envelope()`.
          Keep it?
You     keep it
Claude  $ precept keep envelope-responses
        Kept -> soft (steered). Convention written to
        .claude/rules/envelope-responses.md (loaded as context next session).
```

Session 2 · acme-api · a new endpoint, fresh session

```
You     add GET /reports/{id}
Claude  Added it. Returned it through the envelope helper to match the
        rest of the API:
          return envelope(report.as_dict())
```

*Payoff:* I never repeated the rule. The convention loaded itself into the new session and shaped the first draft, no block needed.

**3. A fact mentioned once, recalled when it matters.**
*Serves O2 (knowledge) · captured and recalled · R2.1, R2.2*

Session 1 · acme-api

```
You     fyi staging runs on Render, prod is Fly.io (app acme-api). don't mix them
Claude  Noted.
        [Precept] Saved to knowledge: deploy-targets
          staging = Render; prod = Fly.io (app acme-api).
```

Session 2 · acme-api · two weeks and several sessions later

```
You     the staging deploy is failing, can you look at the config
Claude  [Precept] recalled: deploy-targets (staging = Render)
        Checking the Render config for staging, not Fly.io.
```

*Payoff:* two weeks on, I did not re-explain where staging runs. The fact surfaced on its own because the topic was relevant.

**4. A changed preference supersedes the stale one.**
*Serves O2 (knowledge stays current) · SOFT governance · R3.3*

Session 1 · web-app · learning

```
You     I moved all tests to a top-level tests/ tree. put new tests there now,
        not next to the source
Claude  Understood.
        [Precept] This contradicts an existing convention:
          colocate-tests (kept 2026-05, "tests live next to the source").
          Replace it with the new one?
You     yes, replace it
Claude  $ precept govern --supersede colocate-tests place-tests-in-tests-tree
        Archived colocate-tests -> superseded by place-tests-in-tests-tree.
        Recompiled 6 active policies.
```

Session 2 · web-app · fresh session

```
You     scaffold tests for the billing module
Claude  Added tests/billing/test_billing.py under the tests/ tree.
```

*Payoff:* the outdated convention did not linger and fire against the new layout. The catalog reflects how I work now, not how I worked in May.

## KPIs

The key results are qualitative; the numbers live here. A KPI is either a standing dial I watch to keep the system healthy, or the single metric behind a key result. Each is marked live or instrumented (harness built, wiring pending). Unset thresholds are left blank with the reason, not filled with a guess.

Standing dials (live):
- Enforcement scorecard: the real engine run over 25 committed cases as a confusion matrix, no model call, CI-gated. Current: recall 100% (TP 10, FN 0), false-block rate 0% (FP 0, TN 15), bounded to violations it has a rule for. Recall is the metric I push; false-block rate is the guardrail, since a false block is the costly error.
- Learning-loop token cost: tokens spent by detect, compile, and the verdict calls, so the loop's overhead stays visible and throttleable. No target.

The number behind each key result:

| Objective | Key result | KPI | Target | Status |
|---|---|---|---|---|
| O1 | Conveyed once, stays | Recurrence rate of a correction I already gave | Near zero | Instrumented |
| O1 | Learnings hold up | Override or rollback rate of embedded learnings | Low; unset | Instrumented |
| O2 | Retrieved when relevant | Retrieval recall at k in relevant contexts | Unset | Instrumented |
| O2 | Current, not stale | Stale-recall rate | Low | Instrumented |

Two thresholds are unset by design: the override-rate floor needs a usage baseline I do not have yet, and the recall-at-k target is the measurement that settles the semantic-recall open question, so I will not pin it before it runs.

The end-to-end O1 measure, whether enforcement improves adherence, is a paired before-and-after reported with a 95% confidence interval, because agentic evals swing several points run to run. Harness built; wiring is the next milestone.

## Roadmap

I order this by dependency and priority, not by date. The rule I am following: harden the loop that already exists before I widen it. The core learning loop is built; the next phase proves it works and measures what it costs; only then do I add more entity types, a data catalog, and autonomous learning on top of a foundation I trust.

Each phase below is defined by an outcome, not a ticket list. Confidence is highest for Now and decreases across Next and Later; Later is directional and will reorder as my real usage tells me which corrections matter most.

### Now (Built)

Outcome: the core loop runs end to end, and its one measurable guarantee is enforced in CI.

- The full loop is working: detect a candidate correction from a session, review it, keep it, then either enforce it deterministically or steer the agent with it.
- 3 of the 9 planned entity types are implemented: Rule, Knowledge note, and Convention. The other 6 are not built.
- The deterministic enforcement eval is wired and CI-gated, so a kept correction that should be enforced cannot silently regress.
- A full offline, hermetic test suite, plus ReDoS and recursion guards on the matcher path.

This is the smallest version of Objective O1 (direction improving across sessions) that actually holds together. It is real, but it is narrow: it improves behavior only for the correction types the three built entity types cover, and the only property proven automatically today is that enforcement fires.

### Next (In Progress)

Outcome: I can measure that the loop actually changes behavior, and know what the learning flows cost.

Everything in Next hardens the loop that already exists. Nothing here widens scope; that is deliberate.

- Paired before-and-after enforcement eval, live. This is the direct measurement of O1: run the same session with and without a kept correction and show the behavior changed. Today enforcement is proven to fire; this proves it helps.
- Token cost report for the learning-loop flows. A system that runs on every session has to justify its own overhead. I want the cost of detection, review, and compilation visible before I add more flows on top.

The before-and-after eval turns the loop's core unproven assumption (that enforcement improves behavior, not just fires) into a measured property. Widening to more entity types or adding autonomous learning before that check exists would scale an unverified mechanism. I would rather scale a measured one.

### Later (Planned, Not Built)

Outcome: the system compounds knowledge as well as direction (Objective O2), proposes its own improvements under the same review gate, and covers the correction types I actually hit.

These are directional. I am naming them honestly as not built, and the order within Later will follow evidence from my real usage, not this list.

- Typed data catalog. The projects, domains, and people my work operates on, as first-class typed entities. This is the backbone for O2 (knowledge that compounds and is retrieved when it applies) and it does not exist yet.
- Catalog schema versioning and migration. A schema version stamped on every entity card, plus version-keyed forward-migrations, so a change to the card format upgrades accumulated entities instead of stranding them. Reversibility today covers a clean uninstall (N8), not forward-migration of accumulated data.
- Background learning. The system drafts improvement proposals from external best practices on its own, gated by the exact same human review that governs corrections today. Autonomy is deferred on purpose: I only want the system proposing changes once the review gate it depends on is proven.
- The remaining entity types. The other 6 of 9, added in the order the correction types show up most in my real usage, so I build coverage where it pays off rather than for completeness.
- Agentic flows. Govern the workflow, not just the action. Today a rule blocks one call and a convention steers one file; the order above that is the repeatable multi-step loop I run with agents (for example, research fan-out, then adversarial verify, then synthesize). Precept would learn a flow I repeat, scaffold the agent through it, and enforce its structure at the Stop gate, extending today's single-call and trajectory checks from one action to a whole sequence.

The through-line: Now is a working loop, Next makes it measured and affordable, Later makes it broad and partly self-driving. I widen scope only after the foundation under it is one I have verified, not one I am hoping holds.

## Open Questions

These are unresolved design decisions, not planned work. Each names the choice, the options, and the specific evidence or gate that would settle it. Until then, the shipped default is stated first.

1. Semantic recall: does this corpus actually need embeddings? Default today is keyword retrieval (FTS/BM25). The risk is that keyword search misses fuzzy or paraphrased knowledge that never shares a literal term with the query. The alternative is an embedding index, at the cost of another index to build, store, and keep in sync. I will add embeddings only if a Recall@k eval on my own corpus shows keyword search missing relevant entities. The threshold that counts as "missing" is not yet set, so the eval cannot yet return a verdict.
2. Router precision: at what confidence does the router auto-route versus ask me? When a correction is ambiguous across homes (rule vs convention vs skill), auto-routing everything risks silent misfiling; asking on everything defeats a self-improving system. The open decision is where to set that confidence gate, and whether one gate suffices or each destination needs its own. Resolved by measuring routing accuracy against my keep and dismiss decisions.
3. Background-learning trust: is the review gate sufficient at volume? When Precept reads external best practices and proposes entities, every proposal passes my review, so nothing enters unreviewed. The open question is whether that holds at volume: many proposals can each pass review yet still degrade the catalog through redundancy or drift. The decision is what constraint sits alongside per-item review (a proposal budget, a dedup or novelty check, a staging area).
4. Coverage: how do I measure the corrections it missed, including the ones it never flagged? Logging the candidates it declined is biased and expensive: it cannot see the misses it never recognized. Instead, coverage is a periodic audit. Take a random sample of full session transcripts (already on disk), re-label every correction in them with an exhaustive second pass (a lower detection threshold, or a stronger adjudicator model), and measure the fraction the production detector captured. Ground truth comes from the transcript, not from what the detector noticed, so the misses it never flagged are counted. Open: the sample size, the cadence, and the recall bar that counts as healthy.

## Related Documents

This README is the product spec and the entry point, kept deliberately high level. The documents below are the deeper design and decision records. Each is the single source of truth for its topic, so this spec points to it rather than restating it.

- [ARCHITECTURE.md](ARCHITECTURE.md): the module map and the data flow between parts. Go here first to see how Precept fits together and to place any component this spec mentions.
- [docs/ARTIFACTS.md](docs/ARTIFACTS.md): the per-entity specification and status tracker for the nine entity types. Go here for what each entity is, its schema, and whether it is built, in progress, or planned.
- [DECISIONS.md](DECISIONS.md): the load-bearing engineering decisions and their reasons. Go here to understand why the system is built the way it is before proposing a change.
- [docs/ANTHROPIC-CONFORMANCE.md](docs/ANTHROPIC-CONFORMANCE.md): a self-audit against Anthropic's published agent-rules and memory guidance, including the one open retrieval gap.
- [docs/LANGUAGE.md](docs/LANGUAGE.md): the language decision (TypeScript on Bun as the target, Python today), with the July 2026 best-in-class scan, the first-principles characteristic breakdown, and the honest tradeoff against Python.
