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

## Usage Examples

Four representative sessions, written for the experience I am building toward, not today's implementation. Each shows a preference or a fact entering through ordinary conversation, passing my review, and then shaping a later session on its own. The tag names the objective each serves. The first two cover process learning (O1), once from an explicit correction and once from a change I make silently; the last two cover knowledge (O2), a fact I give in passing and research the agent gathers on its own, each saved and brought back when it is relevant again.

**1. A correction I give once keeps holding.**
*Serves O1 · R1.5, R1.16*

Session 1 · acme-api

```
You     the deploy failed, install httpx and retry
Claude  Installing httpx with pip.
You     no, this is a uv project. use `uv pip install`, never plain pip here
Claude  Reran it with uv. Done.
        [Precept] That reads like a standing preference: in a uv project,
        always use uv, never plain pip. Want me to hold to it from now on?
You     yes
Claude  Set. I'll apply it in this project going forward.
```

Session 2 · acme-api · three days later, a fresh session

```
You     add the stripe sdk
Claude  Installing stripe with pip.
        [Precept] Held: this is a uv project, use uv here
        (from the preference you set earlier).
Claude  Reran with uv. Added stripe to the project.
```

*Payoff:* the mistake I corrected once is caught on its own in a new session, before it runs, without me watching for it.

**2. An edit I make myself becomes a standing convention.**
*Serves O1 · R1.1, R1.5*

Session 1 · acme-api

```
You     add a GET /orders/{id} endpoint
Claude  Added it:  return {"id": o.id, "status": o.status}
You     [before committing, I rewrite the return myself:
         return envelope({"id": o.id, "status": o.status})]
Claude  [Precept] You routed the response through envelope() yourself rather
        than telling me to. That reads like a standing convention for this
        repo: API responses go through envelope(). Keep it?
You     yes, keep it
Claude  Kept. I'll follow it here from now on.
```

Session 2 · acme-api · a new endpoint, fresh session

```
You     add GET /reports/{id}
Claude  Added it, returned through the envelope helper to match the rest
        of the API:  return envelope(report.as_dict())
```

*Payoff:* I never stated a rule or even said a word. Precept read the edit I made to its output and carried the convention into the new session on its own.

**3. A fact mentioned once is recalled when it matters.**
*Serves O2 · R2.1, R2.5*

Session 1 · acme-api

```
You     fyi staging runs on Render, prod is Fly.io (app acme-api). don't mix them
Claude  Noted. I'll remember where staging and prod run.
```

Session 2 · acme-api · two weeks and several sessions later

```
You     the staging deploy is failing, can you look at the config
Claude  Staging runs on Render (prod is Fly.io, acme-api), so I'm checking
        the Render config, not Fly.io.
```

*Payoff:* two weeks on, I did not re-explain where staging runs. The fact surfaced on its own because the topic was relevant.

**4. Research the agent runs once comes back when it is relevant.**
*Serves O2 · R2.1, R2.5, R2.7*

Session 1 · acme-api

```
You     before we add tool calling, research the current prompt-injection
        defenses for agent tool inputs and lay out the options
Claude  Here are the main defenses, with tradeoffs:
          - schema-validate and allow-list every tool input
          - quarantine untrusted content: pass it as data, never merge it
            into the instruction
          - tag provenance so downstream steps know what is untrusted
        ...
        [Precept] Saved this to knowledge: prompt-injection-defenses
        (the options and tradeoffs the agent gathered this session).
```

Session 2 · acme-api · three weeks later, building the tool layer

```
You     add the handler that feeds fetched web content into the tool call
Claude  From the prompt-injection research we did earlier, the pattern we
        settled on: the fetched text goes in as data, never merged into the
        instruction, and is schema-validated first. Adding the handler that way.
```

*Payoff:* the investigation the agent ran weeks ago was not thrown away. It came back on its own when I built the feature it informed, so the agent worked from it instead of researching the same thing twice.

## Risks and Mitigations

A pre-mortem: assuming Precept had failed a year into daily use, these are the causes, ordered by impact, each paired with its mitigation. Undecided design forks live in Open Questions.

1. **The learning signal is missed or misinterpreted** (impact: high, probability: medium). Precept's base assumption is that ordinary session activity is a rich enough signal that can be correctly accurately be interpreted by an LLM. It can fail by (1) missing a real preference when the signal is implicit (e.g., text edits) (2) capturing the wrong intent behind a change (3) flattening a conditional preference (do X, except in case Y) into a blanket rule that drops the exception, so the rule over-fires.
   Example: I revert the agent's switch from `requests` to `httpx` because I wanted it in its own PR, and it records "do not use httpx" as a standing preference I never held.

   *Mitigations:*
   - **In-session approval:** I approve each inferred preference at the moment it is discovered. [R1.5, R2.4]
   - **Preference origin is documented:** the excerpt of the sessions that yielded the preference is documented word-to-word so it can be judged. [N6]
   - **Contradiction check:** a new preference is checked against my existing rules, and any conflict is surfaced for me to reconcile before it takes effect. [R1.4]
   - **Stated condition:** every new preference must state the condition it holds under, even when the answer is "always holds," so the model always reasons about potential exception when defining preferences. [R1.3]
   - **Accuracy on weak signals:** weak signals are documented, not dropped, and if resurfaced across sessions are promoted to actual preference. [R1.2, R1.13]
   - **Intent inferred through broad context:** intent is interpreted using the surrounding turns, not a lone action/prompt. [R1.1]
   - **Self-correction:** when I correct an inferred preference at the gate, Precept keeps the delta between what it inferred and what I committed and folds it back into how it infers, so that class of mistake stops recurring: a similar correction becomes an example for the next inference, a correction I repeat becomes a standing rule on the inference step itself, and my keep and dismiss record calibrates its scope. [R1.12]
   - **Hindsight audits:** on a schedule, a random sample of past sessions is re-reviewed with a stronger, lower-threshold pass to catch preferences the live detector missed, recover them, and calibrate the preference detection mechanism. [R1.13]

2. **Mis-enforcement: unwanted behaviors are enforced** (impact: high, probability: medium). A recorded preference can be enforced incorrectly when (1) the enforcement is based on LLM reasoning, which can miss or misinterpret parts of the requirements (2) a preference becomes irrelevant but continues to be silently enforced (3) a preference is inaccurately defined (too blunt / wrongly scoped etc). Mis-enforcement is time and quality consuming, erodes the trust in enforcement and pushes to override or switch it off.
   Example: a rule I set in a shared repo to block direct commits to `main` is applied too broadly and fires in a solo scratch repo, where committing straight to `main` is exactly what I want, blocking every commit until I notice why.

   *Mitigations:*
   - **Prefer a deterministic check:** a model verdict is used only when the requirement cannot be checked mechanically, so most enforcement never runs LLM reasoning and that failure cannot arise there. [R1.16, R1.17]
   - **Fail toward not-enforcing:** a low-confidence or errored verdict defaults to allowing, because a wrong enforcement is the costly error, so an unreliable read degrades to no enforcement rather than a wrong one. [N1]
   - **Judge the whole requirement:** when a verdict is used it runs against the full recorded requirement and the turn's context, not a fragment, so it is not set up to miss a part. [R1.17]
   - **Deliberate authoring:** I approve each rule before it can enforce, with its scope and strength shown, so a blunt, mis-scoped, or over-strong rule is refined or rejected at the gate. [R1.5]
   - **Confirmed in practice before it goes live:** the first times a newly recorded rule would enforce, it tells me what it is about to do and why and asks whether that is what I intended; a no refines the rule, and after three consecutive yeses it becomes fully operational and stops asking. [R1.18, R1.19, R1.20]
   - **Validity bound to an observable justification:** a rule's stated condition doubles as its justification, and when that condition is observable (the project uses uv, we are on the release branch, this config exists) the system checks it and retires or flags the rule when it no longer holds, so the rule expires with the situation that created it rather than on a guess. [R1.3, R1.8]
   - **Contradiction triggers reconsideration:** a conflict, an override of the rule or activity that runs counter to it, flags the rule for re-confirmation. [R1.4, R1.10, R1.11]
   - **One-command override:** I can disable the offending rule immediately, and undoing it is exact. [N8]
   - **Auditable, diagnosable, and self-correcting:** every enforcement records what it did and why, so a wrong one names its rule and its basis (which is what makes override possible) and, once I correct it, feeds back so the same mistake does not recur. [N6, R1.12]

3. **A defined convention fails to be enforced** (impact: medium, probability: high). A learned behavior can be unenforced if it is (1) not retrieved in the relevant context (2) ignored: it is retrieved but overlooked under long or conflicting context.
   Example: in `acme-api` I keep the convention "every endpoint returns through the `envelope()` helper so all responses share one shape." Deep into a long session adding a reporting feature (several new files, many tool calls), the model writes the fourth endpoint and returns a raw dict, skipping `envelope()`, even though the convention is retrieved and sitting in its context: a single standing line loses out to the immediate goal, it was loaded near the top where recall is now weakest, and adherence to any one instruction falls as the context grows.

   *Mitigations:*
   - **Store each preference in the type whose load rule fits it:** a path-scoped rule (loads on the files it governs), a described skill (loads when the task matches its description), or the small always-on core (a few globals), so it enters context when relevant by that type's own mechanism. [R1.6, R1.7]
   - **Author it for adherence:** specific, concise, non-conflicting, and named for how it is matched (correct path globs, or a trigger-rich description), because vague or conflicting instructions are followed arbitrarily. [R1.3, R1.6]
   - **Bounded always-on core:** the always-loaded set is capped and everything else is scoped, since adherence drops as that set grows past a couple hundred lines. [R1.6, R1.7]
   - **Enforce or verify the must-hold few:** a preference that must hold regardless of attention is moved off context into a hook or checked at task end, because context alone cannot guarantee compliance. [R1.16, R1.17]

4. **Behaviors and information become hard to track and use as they accumulate** (impact: medium, probability: high). As the information retained in catalog and the enforced behaviors keep compounding, usability and recall can degrade due to problems such as retrieval precision falling as the index grows, and too much context being injected so that even a retrieved entry loses attention (a model's adherence to any single instruction weakens as the number of instructions in context rises). Where risk 3 is one convention losing out within a single session, this is the corpus as a whole decaying as it accumulates, which makes that failure steadily more frequent and harder to diagnose.
   Example: after months of use the catalog holds a few hundred entries, and many share generic terms like `test`, `error`, or `client`. I start an endpoint that shapes error responses, and the one convention I need, "errors return through the `problem()` helper as RFC-7807", ranks below the retrieval cutoff: a dozen other entries also match on `error` and fill the top-k ahead of it, so it is never injected.

   *Mitigations:*
   - **Governance lifecycle:** decay retires an entry once its stated condition no longer holds, supersede folds a newer entry over the one it replaces, and conflict detection surfaces contradictory entries for me to reconcile, so the catalog is actively curated rather than only appended to. [R1.8, R1.9, R2.9, R2.10, R2.11]
   - **Budgeted always-on core:** the always-loaded set is capped and other artifacts load only when conditions match; most of the catalog therefore stays out of context, and accumulation cannot silently push standing context past the range where adherence holds. [R1.6, R1.7]
   - **Identify and merge dups on creation:** governance above prunes duplicates once they exist; the root fix is to avoid minting them. A candidate that matches an existing entry would update that entry instead of creating a parallel one, so the catalog trends toward one entry per preference rather than a drift of near-copies to reconcile later. [would extend R1.4]
   - **A budget on the slice Precept injects, not just the always-on set:** the cap above bounds what loads natively, but Precept's hook also retrieves and injects a per-prompt slice of its own, the relevant knowledge notes and the conventions it injects by relevance, as `additionalContext`, and that slice can grow long and low-precision as the index grows. Because Precept builds this slice itself, capping how many entries it injects per turn and setting a minimum relevance score is deterministic selection on its own retrieval path. What Claude Code retrieves natively (CLAUDE.md, the scoped rule files, skills matched by description) is not capped here; that is governed by the budget and scoping above and by keeping the corpus small (dedup, ranking, consolidation). [would extend R2.5, R2.7]
   - **Rank by precision signals, not lexical overlap alone:** at scale, keyword score cannot separate the one relevant rule from many generic near-matches. Combining it with scope-specificity (a rule scoped to this exact path or repo outranks a global one), recency, and how many times the rule has been confirmed would lift the precise, live entry back above stale generic ones and into the top-k (an embedding index is one option here). [would extend R2.5; Open Question 1]
   - **Periodic consolidation of the catalog:** beyond retiring entries one at a time, a scheduled compaction would merge clusters of overlapping conventions into a single canonical entry. [would extend R1.9, R2.9]

5. **The system becomes too expensive or too slow** (impact: medium, probability: medium). The learning and enforcement loop leans on AI model calls, which cost both money and time. It can fail by (1) latency: a call that has to run while I am working adds to how long I wait for the turn to finish (2) cost: the calls draw on the same budget and quota I use for my own work, and add up the more I use the system. Enough of either and I stop running it, which halts the compounding.
   Example: a busy week of daily sessions runs up enough model usage that Precept competes with my own coding for the same quota, and the per-turn delay is enough that I set it aside.

   *Mitigations:*
   - **Prefer deterministic enforcement:** the system will enforce by a mechanical check wherever a rule allows one, and call a model only when a rule cannot be checked mechanically, so most enforcement carries no token or latency cost. [N2, R1.16]
   - **Only pay for judgment when it is warranted:** before any model call, a cheap deterministic relevance test will decide whether the turn needs one at all, and when several rules qualify their checks will be consolidated into as few calls as possible rather than one per rule. [R1.17]
   - **Do not re-pay for a settled judgment:** once a rule's judgment is resolved in a session, its outcome will be remembered and reused instead of re-asked each later turn, and an identical recurring situation will reuse the prior verdict rather than spend a fresh call. [R1.17]
   - **Keep the costly passes off the turn:** reading a finished session and turning kept corrections into rules will run in the background, off the interactive turn, so their cost never becomes latency I feel. [R1.1, R1.5]
   - **A ceiling I control:** the learning loop can be throttled or switched off entirely with a single control, bounding its cost and latency by choice, while enforcement of already-learned rules keeps working. [N4]
   - **Track cost and latency, and alert on thresholds:** the system will measure both the loop's spend and its added delay and raise an alert when either crosses a set threshold, so a step that grows too expensive or too slow surfaces on its own and can be tuned before I would abandon it. [KPI: learning-loop token cost]

## Functional Requirements

**R1: Processes.** *The platform's agentic processes and output quality improve with each session, from my explicit direction and from the implicit signals in every interaction.*

*Learning*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R1.1 | Precept infers a candidate preference from explicit direction and from implicit signals in a session: an instruction, a correction, an edit to its output, or a repeated choice. | Inference test over explicit and implicit signals |
| R1.2 | When the evidence for a candidate does not identify a single clear intent, Precept records no preference. | Abstain-on-unclear-intent test |
| R1.3 | Precept records the condition a preference holds under, stating it even when that condition is "always". | Stated-condition test |
| R1.4 | Before a candidate preference takes effect, Precept checks it against the preferences already recorded and surfaces any contradiction for reconciliation. | Pre-approval contradiction test |
| R1.5 | Once approved, Precept carries a preference into later sessions, so it does not have to be conveyed again. | Cross-session persistence test |

*Application*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R1.6 | Precept applies a preference only where its recorded condition holds: a repo, a language, a kind of file, or a named situation. | Scoped-application test |
| R1.7 | While a preference's recorded condition holds, the preference takes effect in the agent's work without being restated. | In-context adherence test |

*Currency and accuracy*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R1.8 | When the condition a preference holds under stops being true, Precept proposes retiring it for confirmation, so a way of working that no longer applies stops showing up. | Retirement-proposal test |
| R1.9 | When a newer preference replaces one already recorded, Precept proposes superseding the older one for confirmation. | Supersede-proposal test |
| R1.10 | When a recorded preference is explicitly overridden, Precept flags it for re-confirmation. | Override-triggers-reconfirmation test |
| R1.11 | When work repeatedly diverges from a recorded preference, Precept flags it for re-confirmation. | Divergence-triggers-reconfirmation test |
| R1.12 | When one of its inferences is corrected, Precept applies that correction to later inferences drawn from the same kind of signal. | Correction-reapplication test |
| R1.13 | On a recurring schedule, Precept re-examines past sessions to recover preferences it missed. | Missed-preference recovery test |

*Control*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R1.14 | Precept exposes every preference and every piece of knowledge it has recorded for review. | Full-catalog inspection test |
| R1.15 | Precept removes any recorded preference or knowledge on request. | Removal test |

*Enforcement: the subset that must always hold*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R1.16 | Where a preference must hold in every case and can be checked mechanically, Precept enforces it deterministically, without the model in the loop. | Deterministic-enforcement test |
| R1.17 | Where a preference must hold in every case but cannot be checked mechanically, Precept checks it at the end of every turn. | Turn-end check test |
| R1.18 | When a preference that must hold in every case first applies, Precept states what it would enforce and why, and asks whether that was intended. | First-encounter explain-and-ask test |
| R1.19 | When the answer is that it was not intended, Precept narrows the preference's recorded condition. | Narrow-on-no test |
| R1.20 | After a configured number of consecutive confirmations, Precept enforces the preference without asking again. | Graduation-after-threshold test |

**R2: Knowledge.** *The knowledge the platform comes across while working compounds and stays current with each session, and is retrieved for both me and the agentic processes whenever it applies.*

*Capture*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R2.1 | When knowledge the work depends on beyond the current session appears, whether stated directly or built up by the agent while working, Precept captures it as a candidate. This covers a single fact, a body of research, and anything in between. | Capture test across short and long-form knowledge |
| R2.2 | When the evidence for a candidate does not establish what it says or whether it holds, Precept records nothing. | Abstain-on-unestablished-knowledge test |
| R2.3 | Precept records the condition under which recorded knowledge still holds. | Validity-condition test |
| R2.4 | Once approved, Precept stores knowledge so later sessions draw on it instead of working it out again. | Cross-session persistence test |

*Retrieval*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R2.5 | While recorded knowledge is relevant to the active session, Precept surfaces it to the agent. | Relevance-retrieval test |
| R2.6 | Precept surfaces recorded knowledge on direct request, not only through the agent. | On-demand recall test |
| R2.7 | When only part of a long record applies, Precept surfaces that part rather than the whole record. | Partial-surfacing test on a long record |
| R2.8 | Precept does not surface knowledge that has been retired or superseded. | Stale-exclusion test |

*Currency*

| # | Requirement | Verified by |
|---|-------------|-------------|
| R2.9 | When newer knowledge replaces something already recorded, Precept proposes superseding the earlier record for confirmation. | Supersede-proposal test |
| R2.10 | When the condition recorded knowledge holds under stops being true, Precept proposes retiring it for confirmation. | Retirement-proposal test |
| R2.11 | If two pieces of recorded knowledge contradict, Precept surfaces the conflict for reconciliation. | Conflict-detection test |

### Realization notes

The mechanism the requirements deliberately abstract over. Typed entity, tier, and commit target live here, because they are how, not what.

- **Structure and types:** preferences and knowledge are stored as individually addressable typed entries; that structure is what makes currency (R1.8, R1.9, R2.9 to R2.11) and precise retrieval possible. Nine entity types with commit targets: Rule to hooks and `permissions.deny`, Knowledge note to a local index, Convention to `.claude/rules/*.md`, Skill, Agent persona, Output style, Slash command, MCP config, Permission profile.
- **Placement and retrieval (R1.7):** Precept commits each steering preference to the Claude Code artifact whose native load rule surfaces it in the right context (a path-scoped rule file, a skill described for the task, or the small always-on core), so surfacing leans on Claude Code's own loading, not a Precept-built retriever. Only the knowledge index (R2.5) is Precept-retrieved.
- **Long-form knowledge (R2.7):** a research note is stored whole so its reasoning survives, and surfaced in the part that applies, so a long record can enter a session without displacing the work. Section-level addressing is what makes this possible.
- **Steering vs enforcing (Non-Goal 2):** most preferences steer through context (R1.7); only one that must hold in every case is enforced (R1.16, R1.17). That set stays small on purpose.
- **Context budget:** a size cap on the always-loaded set, everything else loaded only in scope, so adherence (R1.7) holds as the catalog grows. Risks 3 and 4 point here.
- **Enforcement:** targets are a hook decision, a `permissions.deny` rule, or a subagent tool-scope; the R1.17 check runs every turn, only the verdict is a model call.
- **R1.13 schedule** and the **R1.20 confirmation threshold** are tunable parameters, which is why neither number appears in the requirement.

## Non-Functional Requirements

These are the properties that have to hold for a system that learns from my sessions, rewrites my agent's configuration, and runs inside my coding tool to be one I can leave running unattended. Each is stated as a property with a verification method and a status (built, partial, designed, planned). The frame is ISO/IEC 25010:2023; the two attributes it does not cover well for a self-improving agent (auditability and accountability) are stated explicitly rather than folded into security.

| # | Quality | Requirement | Verified by | Status |
|---|---------|-------------|-------------|--------|
| N1 | Reliability | The runtime fails open. No error, missing key, or unreadable cache ever blocks a session; the worst outcome of a Precept fault is that enforcement does not fire, never that my session wedges. Failing open has one downside worth catching: it can let the learning loop go silently inert (an expired credential once left it dead for weeks), so each learning flow records when it cannot reach a model and a diagnostic reports an unreachable backend, surfacing a dead backend instead of letting it pass for a quiet session. The learning side takes the opposite stance on purpose: detection fails closed, so an error there records nothing rather than a wrong preference. | Fault-injection tests at every hot-path seam (unreadable cache, malformed event, model error) assert an allow decision; a test asserts a flow that cannot reach a model records the failure while still failing open; a test asserts a detection error records nothing. | built |
| N2 | Performance | The enforcement hot path is stdlib-only: no model call, no network, no third-party import. It runs as a fresh process on every guarded tool call, so its cost is a bounded local computation, not a round trip. | A retrieval and enforcement perf test; the import graph of `enforce.py` is asserted to exclude the SDK and pydantic. | built |
| N3 | Safety | Model-authored logic can never harm the machine. It executes only as data through a fixed interpreter (no `eval` or `exec`); regex is ReDoS-guarded by a compile-time reject of catastrophic forms and a runtime wall-clock bound that fails to "no match"; nested inference is recursion-guarded. This is ISO 25010:2023 fail-safe: the failure of a model-generated artifact degrades to inert, not dangerous. | Adversarial tests: a catastrophic pattern is rejected at compile and abandoned under bound at runtime; a fork-bomb-class correction cannot compile to executable code. | built |
| N4 | Security | The enforcement plane sends nothing off the machine and holds no credential; the learning plane's model access is the only egress and is disabled by one environment variable. Local-first is the default, not a setting. | The hot path has no network import (shared with N2); a test asserts the learning loop is inert when the disable flag is set. | built |
| N5 | Integrity | An entity cannot claim enforcement it cannot deliver. The HARD/SOFT boundary is validated in the type system: a HARD tier on an event that physically cannot block a call is a construction-time error, not a runtime surprise. A correction earns determinism only by compiling to a matcher that passes a typed validator; otherwise it stays soft. | A type-level test asserts HARD on a non-blockable event raises. | built |
| N6 | Auditability | Every enforced decision and every learned entity is traceable to its origin. `precept why` shows where a lesson came from and why it is trusted (the provenance gate: user-typed turns only); each policy match writes an append-only decision-log line; the verdict prompt for a judgment rule is stored on the entity's own card. Nothing enforces anonymously. | Tests assert a match appends a well-formed log line and that `why` resolves provenance; the log is the source of the live fire counts governance reads. | built |
| N7 | Accountability | Precept has no autonomous write path to my agent's behavior. Every behavioral change and every catalog entry originates from a proposal that was approved. The functional requirements specify the gate; this is the guarantee that there is no path around it. | A test asserts that no path activates a behavioral change or writes a catalog entry without a recorded approval. | built |
| N8 | Reversibility | All writes to ~/.claude are atomic (temp-in-same-dir, fsync, rename) and exactly inverse on uninstall, so adopting Precept is a decision I can fully undo. Every commit target is backed up before it is touched, and a retired entry is archived with a back-pointer rather than hard-deleted, so retirement is recoverable too. | Install and uninstall round-trip tests assert the tree returns to its pre-install state byte-for-byte; a test asserts a retired entry stays recoverable. | built |
| N9 | Testability | The model client is injectable at every AI seam, so the entire suite runs offline and hermetic, with no key and no network. Non-determinism is confined to the seams a fake client replaces. | CI runs the full suite with no `ANTHROPIC_API_KEY` and no network; a fake client is the default in tests. | built |
| N10 | Privacy boundary | Learned content (the catalog, local state, any vault) lives outside this repository, and the boundary is enforced, not asserted: a CI test fails the build if a populated catalog card, local session config, or personal marker (home paths, phone patterns, vault mounts) is ever tracked. The public code plane never contains my private data plane. | `tests/test_repo_privacy.py` runs in CI and fails on any tracked private artifact. | built |

A note on what is deliberately absent. There is no availability SLA, no horizontal-scalability target, and no multi-tenant isolation requirement, because there is one user on one machine and the system is allowed to be absent (it fails open by design, N1). Adding those would be answering a question nobody asked. The one attribute I would add before any other user touched this is a catalog schema-version and migration guarantee: today the reversibility guarantee (N8) covers a clean uninstall but not forward-migration of a catalog that has accumulated for months if the card format changes. I name it here as a known gap rather than imply it is handled.

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
