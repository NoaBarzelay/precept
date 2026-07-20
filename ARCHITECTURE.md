# Architecture

How Precept is built to satisfy the product spec in [README.md](README.md). It states design intent for the TypeScript rebuild, not the state of the current Python code. The rebuild is sequenced as a strangler over the shared catalog rather than a rewrite (section 10), so this describes the target the migration converges on, and a working system exists at every step along the way.

Read the README first. This document names the mechanism each requirement gets and where it lives; it does not restate requirements. Bracketed tags refer to the README's numbering.

## 1. Scope and context

Precept is a single-user tool beside Claude Code on one machine. It has four boundaries and no others.

| Boundary | What crosses | Direction |
|---|---|---|
| Claude Code hooks | Session events in, decisions and injected context out | Both |
| Claude Code owned files | Entries written as instruction files, rule files, skills, settings | Out |
| Anthropic inference | Candidate extraction, judgment verdicts | Out and back, one module only |
| Local disk | Catalog, derived projections, operational state | Both |

One machine, one user, one agent host, no server [Non-Goals 4, 5]. That removes authentication and multi-tenancy.

It does not remove concurrency. Four writers run against the same state by design: the interception path, the injection path, the asynchronous observation path, and the scheduled maintenance path, multiplied by however many Claude Code sessions are open. Section 7 states the write model.

## 2. Constraints

Fixed inputs. The architecture is shaped around these; it does not choose them.

- **The host contract is unversioned and has changed before.** Every integration point is a moving target with no compatibility promise.
- **TypeScript on Bun**, decided in [docs/LANGUAGE.md](docs/LANGUAGE.md).
- **Enforcement runs inside the user's own latency budget.** The measured process floor is 26 ms before any of Precept's code runs.
- **Inference draws on the same subscription quota as the user's own work.**
- **The catalog may sit in a cloud-synced folder.** Anything with a live database file must not.
- **A model authors part of the system's content**, and session content can be adversarial. Both are untrusted input.

## 3. Architectural drivers

Five quality attributes shape the structure, each with a measure so it can be tested rather than asserted.

| # | Scenario | Response measure | Requirements |
|---|---|---|---|
| D1 | A guarded tool call arrives mid-session and an entry applies | Added latency at or below 50 ms p50 and 120 ms p95, with no model call and no network | N2, R1.17 |
| D2 | Any part faults during a session: unreadable file, unparseable event, unreachable model | The call proceeds, and the failure is recorded against the entry that did not fire | N1, N3 |
| D3 | An entry is recorded claiming it always holds | It enforces deterministically only if its check is well-formed and matches at least one concrete call, drawn from recorded history or an example confirmed at review (5.1); otherwise it degrades to guidance and is labelled as such | N5, Non-Goal 2 |
| D4 | The catalog grows from ten entries to several hundred | What Precept injects does not grow with it, and both what it injects and what it writes into always-loaded targets stay within stated caps | N9, R1.8, Risk 4 |
| D5 | An inferred preference is about to change agent behaviour | It cannot reach enforcement without a recorded decision, and the reliability of that decision is measured | N7, Risk 1, Risk 2 |

Three non-functional requirements are structural and are not covered by D1 to D5: N10 (cost attribution and alerting), N12 (forward migration), N13 (verdict stability). Sections 7 and 9 carry them.

## 4. Solution strategy

**D1, latency.** The interception path links no model client, no schema library, and no catalog writer, and reads a compiled projection through a fixed evaluator. Enforced by a dependency rule and a startup budget test (section 9), because a single stray import regresses it without failing anything else. Evaluation cost is not the constraint: at several hundred entries, evaluating the whole projection is below measurement noise against the 26 ms floor.

**D2, fault behaviour.** Everything that runs during a session fails toward allowing and records the failure. Fail-open is a defect in the general case (CWE-636; OWASP's 2025 list names mishandled exceptional conditions), justified here because the threat model is the user's own drift, not an adversary, and a wedged session costs more than a missed block. That justification collapses if failures are silent, so the record and the error budget (section 7) are part of the mechanism.

**D3, enforcement that cannot overclaim.** Two languages, not one: a small, auditable check language for anything that blocks, and free text for anything that only steers. A check is allowed to enforce only once it is well-formed and matches at least one concrete call, from recorded traffic or an example confirmed at review, so an entry never claims enforcement it cannot demonstrate. A preventive rule whose blocked call has never occurred is validated by that reviewed example, not stranded as guidance. Section 5.1 specifies the language and how its checks are validated against evidence. An entry whose intent the check language cannot express does not get a weaker check; it becomes guidance.

**D4, bounded context.** Two levers, because there are two mechanisms. What Precept injects passes through one module that applies a cap and a relevance floor. What Precept writes into always-loaded targets is capped at authoring time by the same module that writes it.

**D5, approval integrity.** Approval is structural: the modules that write to targets Claude Code reads take a decision record as an input and have no other entry point. The gate is then designed against a documented failure mode and instrumented so its decay is visible.

## 5. Building blocks

### 5.1 The check language

What a blocking check can say, and how the system confirms a check can deliver what it claims before it blocks.

**Two tiers, because they have different budgets.** A *lexical* check runs at interception, in front of the call, and must fit D1. A *structural* check needs a parsed syntax tree, which means a parser and an arbitrary parse on a path with a 26 ms floor, so it runs at turn end instead, where a parse and a seconds-scale budget are already accepted. The split is driven by budget alone.

**Fact base, lexical tier.** A check is a formula over one immutable, typed record assembled by `host` before evaluation. It may reference: the tool name; the typed fields of that tool's input; the resolved path, repository, and branch; and the session's permission mode. Repository and branch are resolved by `host` into the record, which is the one filesystem read the interception path makes and is budgeted in 5.4. The formula itself may not touch the filesystem, the network, or the clock. Facts are collected first, then the formula is evaluated, so evaluation is pure and total.

**Grammar, lexical tier.** Quantifier-free formulas: conjunction, disjunction, negation, over atoms from a closed set.

| Type | Permitted atoms |
|---|---|
| Boolean | equality |
| Finite enum | equality, membership |
| Integer | equality, linear comparison |
| String | equality, membership in a literal set, prefix, suffix, substring containment, regex (linear-time engine) |
| Path | glob over segments |

Substring containment is required. The README's first usage example is "never plain pip here," and real invocations are `cd api && pip install x`, `python -m pip install x`, `sudo pip install x`. None matches on a prefix or a suffix. Dropping it would make the deterministic tier fail on the canonical case.

A regular-expression atom over string fields is available, evaluated by a linear-time engine only, never a backtracking one, so a model-authored pattern cannot cause a runtime denial of service. Excluded from the grammar: iteration, recursion, user-defined functions, and arithmetic beyond linear comparison. The grammar stays small because a small language is auditable and cheap to evaluate; it does not need to be provable, since validation does not rest on a proof.

**A check is validated against recorded traffic, not proved.** The symbolic alternative, reachability by satisfiability, contradiction by unsatisfiable conjunction, subsumption by language inclusion, is an automata or SMT problem over strings, globs, and integer constraints. In a TypeScript build that means a multi-megabyte solver too heavy for any budget or a hand-rolled automata engine large enough to dominate the schedule, and it answers only three of the four questions the gate needs. Evidence answers all four and costs a corpus scan.

The system records every guarded tool call as evidence, so a check is validated against that history:

| Question the gate must answer | Symbolic form | Evidence form |
|---|---|---|
| Can this check ever fire? (N5, D3) | Satisfiability | Does it match a concrete call, from history or a reviewed example? |
| Do two checks contradict? (R1.4) | Unsatisfiable conjunction | Did they disagree on any recorded call? |
| Is this check already covered? (R1.4, Risk 4) | Language inclusion | Did one check's matches contain the other's over history? |
| How broad is this check? (the review gate) | Not expressible symbolically | How many recorded calls would it have fired on, and which? |

The fourth question has no symbolic form and is the one the review gate depends on. Well-formedness stays a sound syntactic type check against the fact schema; the three semantic questions run against evidence.

**The cost.** Evidence-based validation is unsound in the formal sense: a contradiction or a redundancy between two checks that never co-occurred in recorded history is not detected. The runtime combination rules in 6.4 (fail toward not enforcing, apply no rewrite on a live collision) are the safety net for what validation misses, so authoring-time validation is an advisory pass over the past, not a guarantee about the future.

At the review gate, a check's recorded history stands in for its rationale: the gate presents "this rule would have fired on 14 calls in the last month, here are three of them, should it have blocked these?" That is cognitive forcing by a judgment on real cases, faster than reading a rationale and not subject to the explanation-acceptance effect a rationale panel triggers (section 11). It also lets a probationary rule accumulate its confirmations retroactively from history, so a rule graduates without ever interrupting a live session (6.1).

**Growth rule.** The grammar stays small on purpose. Because validation rests on evidence rather than a proof, growth is governed the same way: a proposed atom is admitted only if the validation corpus scan still runs within its budget over the golden entry set (section 9), and every atom ships with recorded positive and negative examples. Structural predicates live in an enumerated, code-authored library, each with the same examples as tests.

### 5.2 Modules

Boundaries are drawn around what changes at a different rate from its neighbours, and each names the decision it hides. A boundary that hides nothing nameable is a file.

| Module | Decision it hides | Rate of change |
|---|---|---|
| `domain` | What an entry is: types, the check language and its evaluator, validity, lifecycle state, placement policy | Low. The durable asset |
| `store` | On-disk layout of all three tiers in section 7, including the review queue and the decision log; atomic writes; locking; schema version; migration | Medium |
| `retrieve` | How entries are indexed, ranked, budgeted, and assembled for injection | Medium |
| `host` | The entire Claude Code contract: event shapes, decision format, file locations, settings precedence, target capabilities | High |
| `infer` | Model, prompt, schema, backend, and how past corrections shape the next inference | High |
| `gate` | How review is presented, recorded, and measured | Medium |
| `eval` | How enforcement quality and retrieval quality are measured, including the golden set and the labelled relevance set the recall and stale-recall KPIs read from | Medium |
| `cli` | How the catalog and its health are inspected and operated | Medium |
| `record` | Provenance, telemetry, cost, latency; writes through `store` | Low |

`host` and `infer` are anti-corruption layers in the strict sense: nothing outside them sees the foreign shape. The host contract having already moved once is the argument for the first; a model's output being untrusted is the argument for the second.

The decomposition departs from a module-per-processing-step layout in two places. There is no separate evaluator module: defining the check language and evaluating it change in the same commit, so splitting them decomposes by processing step rather than by rate of change. There is no separate placement module: which targets exist, where they live, when they load, and what they cap is `host` knowledge, so `host` exposes target capabilities as typed data and placement is a pure function in `domain` over that data.

### 5.3 Dependency rule

```
Modules (the tiered core):
  domain          imports nothing
  store           imports domain
  host, record    import domain, store
  retrieve        imports domain, store
  infer, gate,
  eval            import domain, store, retrieve, record

Entrypoints (orchestrators over the modules):
  injection       imports host, retrieve, domain
  cli             imports gate, infer, host, retrieve, store, domain
  interception    imports host, domain, record (the thin hot path)

infer  is the only module that may reach the network
host   is the only module that may know the Claude Code contract
store  is the only module that may write to disk
```

Modules form the tier; entrypoints drive them. An entrypoint may import more of the modules than a module may, because it is the orchestration layer, not a peer. The one entrypoint held to the module discipline is `interception`, whose whole point is to stay thin. The dependency rule is a CI fitness function (section 9) that resolves every relative import to its module and rejects a crossing the table above does not permit.

`record` is not a leaf. Its contents live in operational state, whose layout, atomicity, and locking are `store`'s hidden decision, so `record` writes through `store` like everything else. Making it a leaf would put a second uncoordinated writer on the tier section 7 exists to close.

The interception path is `host` plus `domain` plus a read-only view of the compiled projection plus `record`. `record` is on that list deliberately: D2 requires a failure record on every fault, so forbidding the import would forbid the mechanism. The path may not import `infer`, `gate`, `retrieve`, a parser, or any schema library. Checked in CI.

### 5.4 Entrypoints

| Entrypoint | Host events | Runs | Budget |
|---|---|---|---|
| Interception | PreToolUse | Lexical checks only | D1: 50 ms p50, 120 ms p95. No model, no network, no parser |
| Turn end | Stop | Structural checks, then model verdicts | Relevance test at 10 ms; 3 s p95 when a verdict runs |
| Injection | SessionStart, UserPromptSubmit | Retrieval and assembly | Well below the host's prompt-submit timeout |
| Observation | PostToolUse, PostToolUseFailure, PermissionDenied, SessionEnd | Evidence capture | Asynchronous, off the turn |
| Maintenance | None, scheduled | Sections 6.5 and 6.7 | Off the turn entirely |
| Command line | None | Section 6.6 | Irrelevant |

Interception and turn end are separate entrypoints because they have opposite constraints: one must never call a model or a parser, the other exists to do both.

**Most turns should invoke Precept zero times.** Claude Code hook registration is scoped by tool name, so `install` regenerates the registration to match only the tools that some entry actually references. A session with no entry touching `Read` never spawns the interception process on a `Read`. This does more for felt latency than any per-call optimization, because the cheapest call is the one that never happens, and it is why the budget below is about the calls that do fire rather than about amortizing over all of them.

**The D1 figures are targets to be validated, not derivations.** The 26 ms floor is measured; the remaining 24 ms covers a stdin read, a JSON parse, the repository and branch resolution, opening and reading the compiled projection, evaluation, and emitting the decision. That is plausible only if the projection is a plain JSON file, which is why it is one: a SQLite open would spend most of the remainder, and prepared-statement caching never pays under spawn (section 8). Two things the figures do not capture: matching hooks run in parallel with no ordering guarantee, so what the user feels is the maximum across every registered hook rather than Precept's alone; and the relevance test at turn end runs on every turn, so it carries its own budget line above. If the section 9 test fails against these figures, that is the trigger for the warm-daemon escape hatch in section 8, not a licence to raise the numbers.

## 6. Runtime views

### 6.1 Write path

One spine carries both objectives. A preference [R1.1] and a piece of knowledge [R2.1] differ in what is extracted and where it is placed, not in how it is reviewed, recorded, or kept current, so the path below is written once.

```
session activity
   |  observation, asynchronous
   v
EVIDENCE          append-only, immutable, provenance-tagged by source
   |  infer
   v
CANDIDATE
   |  abstain        evidence does not identify one intent: discard with a record   [R1.2, R2.2]
   |  novelty        duplicates an existing entry: fold into it, do not queue
   |  corroboration  support estimated over distinct causes, not repetitions
   |  contradiction  checked against recorded entries                               [R1.4]
   v
REVIEW QUEUE      durable, survives the session that created it
   |  gate: keep, dismiss, or correct                                               [N7]
   v
DECISION RECORD   immutable: proposed, committed, and the delta between them
   |  place, then compile
   v
ENTRY             carried into later sessions without being conveyed again  [R1.5, R2.4]
   |
   v
ENTRY (probationary) --three consecutive confirmations--> ENTRY (operational)       [R1.19-R1.21]
   |
   v
PROJECTIONS       check cache and search index, both rebuildable
```

**Signals observed.** Explicit direction is the easy half. The implicit half is what the objective actually rests on, so the observation path captures four kinds: an instruction, an explicit correction, a repeated choice, and the user silently editing the agent's output. The last one is the README's own second usage example and it needs a mechanism the others do not: the observation path records what the agent wrote, and a post-session pass diffs that against the file's final state, so an edit the user never remarked on becomes evidence [R1.1].

Six properties of this shape carry the design.

**The four record layers stay separate.** Evidence, candidate, decision, and entry are distinct and never collapsed. Correcting the inference [R1.13] needs the delta between proposed and committed; re-examining past sessions [R1.14] needs raw evidence still present when the extractor improves. Collapsing the layers forecloses both.

**Evidence carries provenance, and provenance gates enforcement.** Only a user-typed turn may source a blocking entry. This is the answer to the injection threat: a file or web page read during a session can contain text designed to induce a permissive entry, and since committed entries are written into instruction files, skills, and settings, an accepted entry persists into every future session. Logic-as-data [N3] does not address this; the provenance gate does.

One consequence is intentional. A silent edit to the agent's output is not a user-typed turn, so the README's second usage example can source guidance but never a blocking entry. That is the correct trade: an inferred-from-silence signal is exactly the kind that should steer rather than block.

**Novelty is checked before the reviewer is.** Reviewer attention is the scarce resource, and folding on creation is the root fix for catalog sprawl, where governance is only cleanup [Risk 4].

**Repetition is not corroboration.** One claim appearing in five sessions may be five independent signals or one shared cause seen five times. Support is estimated over distinct causes; a candidate whose support is dependency-risky routes to review instead of being promoted or dropped [Risk 1].

**Nothing enters enforcement operational.** A probationary entry emits `ask`, never `deny`. On first application it states what it would enforce and why and asks whether that was intended [R1.19]. A no sends it back for narrowing [R1.20]: `infer` proposes a narrowed check from the counterexample that just occurred, the proposal re-enters the same gate, and the narrowed check is re-validated against recorded history (5.1) before it can be committed, so narrowing cannot smuggle in a check that never fires. A configured number of confirmations, defaulting to three, graduates it, and those confirmations may be satisfied retroactively from recorded history, not only from live encounters, so a rule can go operational without ever interrupting a session [R1.21]. The commit point is the entry card, per the lock order in section 7, so two parallel sessions cannot both land the final confirmation.

### 6.2 Inference

The write path is the structure; inference is what fills it, and it is where the primary objective lives. Enforcement is a downstream consumer of what inference produces. Everything here runs off the interactive turn.

**The evidence record.** One immutable, append-only record per candidate-bearing moment. It holds the surrounding turns verbatim (not a summary, because summarizing at capture time destroys the raw signal that R1.14's re-examination depends on), the provenance tag (user-typed, agent-authored, or tool-observed), the session and repository identifiers, and, for a silent-edit signal, both the agent's output and the file's final state so the diff is reconstructable later. Evidence is never rewritten, only appended to and read from.

**Inferring a candidate.** A candidate is drawn from a window of evidence, not a single turn, because intent lives in the exchange around an action, not the action alone [R1.1]. Each candidate carries: the preference or fact stated positively, the condition it holds under (5.1, stated even when the answer is "always" [R1.3, R2.3]), the evidence span it was drawn from, and the signal kind (instruction, correction, repeated choice, silent edit).

**Abstention is the default, not the exception.** When the evidence window does not resolve to a single intent, the candidate is discarded with a record of why, never queued [R1.2, R2.2]. The threshold that decides "resolved" is one scalar per signal kind, set low for explicit corrections (which rarely mislead) and high for silent edits (which frequently do). Those scalars are the calibration surface in 6.7. Confidence is grounded in observable features of the evidence (is there an imperative, is there a verbatim quote, did it recur), not an LLM self-report, because verbalized model confidence is miscalibrated.

**Corroboration counts distinct causes, not observations.** The failure this prevents is promoting something the user never held because one shared cause was seen many times [Risk 1]. Two pieces of evidence corroborate only if they are causally independent: different sessions, different repositories, different prompt lineage. Evidence sharing a cause (the same file read twice, the same instruction echoed) counts once. A candidate below the independence bar is not dropped; it is held as weak and promoted if an independent signal later arrives, which is what lets a preference expressed faintly and repeatedly still surface [R1.14].

**Long-form knowledge is captured whole and surfaced in part.** A single fact and a body of research enter the same path [R2.1]; they differ only in that a long record is sectioned at capture (by heading) so retrieval can return the applicable section, not the whole document [R2.7], which is also what keeps a long record from blowing the injection budget.

### 6.3 Read path

Two mechanisms, and conflating them produces a promise the architecture cannot keep.

| | Precept injects | Claude Code loads |
|---|---|---|
| What | The per-prompt retrieved slice | Instruction files, scoped rule files, skills |
| Bounded by | Cap and relevance floor, applied directly | The cap `domain` enforces on what Precept writes into always-loaded targets |
| Requirements | N9, R2.5, R2.7 | R1.6, R1.7, R1.8 |

Both columns are capped, by different means. The right column's cap is a stated line budget on Precept's own contribution to the always-loaded set, checked when the entry is written, not a hope that the set stays small.

**Placement inputs** are the entry's scope, its trigger, whether it must survive compaction, and its size. The host facts that decide this live behind `host` as versioned, fixtured data, because constraint 2 says they move:

- Root instruction files and auto memory are re-injected from disk after compaction.
- Path-scoped rule files and nested instruction files are lost after compaction until a matching file is read again.
- Skill bodies are capped at 5,000 tokens each and 25,000 total.

An entry that must hold across a long session therefore cannot be a path-scoped rule. A long knowledge record cannot be a skill.

**Partial surfacing** [R2.7] is section granularity: a long record is indexed and retrieved by section, with sections delimited by heading. Retrieval filters on validity, so retired and superseded entries never enter a result set [R2.8].

**Authoring for adherence.** Placement and size caps are half of Risk 3's mitigation; the other half is that the text itself has to be followable, since vague or conflicting instructions are followed arbitrarily. Compiling an entry to its target therefore checks what can be checked mechanically: that a path-scoped rule's glob actually matches files in the repository it claims, that a skill's description contains the triggers it needs to be selected on, that the entry states one behaviour, not several, and that it does not contradict a co-located entry. A failure here is a compile failure surfaced at the gate, not a warning after the fact.

### 6.4 Guard path

```
tool call -> host: assemble facts -> domain: evaluate applicable entries -> host: emit decision
                                              |
                                     no match: allow
                                     fault:   allow, record against the entry   [N1]
```

The evaluator is fixed code over data; an entry is never executable, so a wrong model-authored entry degrades to no effect instead of an action [N3]. It bounds-checks its inputs despite those inputs having passed authoring-time validation, because the reference failure in this class (CrowdStrike, July 2024, 8.5 million machines) was a missing bounds check in an interpreter reading content that had passed validation.

**Decision combination.** Four outcomes, ordered `deny > ask > rewrite > allow`, as in [DECISIONS.md](DECISIONS.md). The strongest outcome across applicable entries wins. `ask` is what a probationary entry emits [R1.19]; only an operational entry may rewrite.

Rewrite is the one outcome that carries data, so it is the one that could break order independence: two entries rewriting the same tool input do not commute in general. This is handled primarily at runtime and advised at authoring time.

- A rewrite action names the single input field it targets. Two rewrites conflict only if they target the same field.
- **At runtime, a field targeted by more than one applicable rewrite is left unrewritten and the collision is recorded** [N1]. This is the guarantee: failing toward not rewriting is consistent with D2, since a missed correction costs less than a silently mangled tool call.
- **At authoring time**, a proposed rewrite whose target field collides with an existing rewrite on any recorded call is surfaced for reconciliation, so the common case is caught before it ships. This is the same evidence scan as every other check in 5.1, and it is advisory: it cannot see a collision that has not happened yet, which is exactly why the runtime rule above is the real safety net.

So the ordering property holds unconditionally at runtime: **the outcome does not depend on evaluation order**, because two rewrites that would disagree produce no rewrite rather than an order-dependent one, and **adding a deny can never weaken enforcement.** Neither is general monotonicity. Exceptions to a preference [R1.3, R1.20] are expressed only as narrowed conditions on the entry itself, never as a permit overriding a deny.

Rewrite is what makes the README's first usage example read as written: the agent's call is corrected in place instead of denied and retried, one fewer round trip and the difference between a tool that corrects and one that only refuses.

Where a requirement cannot be checked mechanically, the verdict runs at turn end [R1.18], gated by a deterministic relevance test, consolidated across applicable entries, and cached by fact-record hash so a repeated situation reuses its verdict across sessions instead of re-paying for it. That makes repeats identical by construction; it does not make a first verdict on a novel record deterministic, which is why N13 is measured as agreement across samples rather than asserted [N13].

### 6.5 Maintenance path

Scheduled, never on a turn.

- **Validity sweep.** Where an entry's recorded condition is observable, it is checked and the entry proposed for retirement when it stops holding [R1.9, R2.10].
- **Supersede and consolidate.** A newer entry folds over what it replaces [R1.10, R2.9]. Consolidation merges overlapping entries deterministically, by delta, never by asking a model to rewrite the corpus: that operation is the documented context-collapse failure mode, and the published results that make it look safe depend on an automated verifier this system does not have. Every consolidation is reversible through the bi-temporal record, and a fitness function asserts no entry's content is lost across a pass.
- **Contradiction detection** across recorded entries [R2.11].
- **Override and divergence detection.** An explicit override or a permission denial flags the entry for re-confirmation [R1.11]. A post-session adherence pass compares session artifacts against applicable guidance entries and flags repeated divergence [R1.12]. That same pass supplies the Risk 3 evidence and the O1 recurrence KPI.
- **Hindsight re-examination.** A sample of past sessions is re-read at a lower threshold to recover what the live path missed [R1.14].

### 6.6 Control surface

The catalog is inspectable and operable without going through the agent, because two requirements are about the user's own access, not the agent's.

- Every recorded entry and every piece of knowledge is listable and readable, with its condition, its status, its provenance, and its enforcement tier [R1.15].
- Any entry is removable on request, which tombstones and purges rather than invalidating [R1.16].
- Recorded knowledge is recallable directly by the user, not only by surfacing to the agent [R2.6].
- Health is readable: the failure counter behind the error budget, the cost ledger, the queue depth, and which entries are probationary.

This is `cli`. The fail-open justification in D2 and the provenance guarantee in N6 both depend on the failure being visible to someone, and nothing else in the architecture shows it.

### 6.7 Correcting the inference

[R1.13] requires a concrete representation. A **delta** is a structured record: the candidate as proposed, the entry as committed, the field-level diff, and the dismissal reason where there was one.

Deltas are consumed three ways, all inside `infer`:

| Mode | Mechanism | Bound |
|---|---|---|
| Exemplar | The most recent k deltas sharing the candidate's signal type and scope are included in the extraction prompt | Fixed k, so prompt size is constant. Recency and exact-match selection deliberately, because a similarity metric over structured deltas would need the embedding index section 8 declines to build |
| Standing instruction | A correction repeated above a threshold compiles to an instruction on the extraction step itself, and is reviewed at the same gate as any other entry | Counted against a stated cap |
| Calibration | Keep and dismiss rates by signal type and scope adjust the abstention threshold | A single scalar per signal type |

The effect is measured, because a stricter inference suppresses true positives as well as false ones: the hindsight audit [R1.14] is the control, since it re-labels sessions independently of what the live detector noticed.

## 7. Cross-cutting concepts

**Concurrency and the write model.** Four internal writers plus however many sessions are open, and a fifth writer that does not cooperate.

- **Read-modify-write is locked end to end, not just at the write.** An advisory lock spans the read and the write, and every card carries a version that must match at commit. Atomic rename alone gives crash safety and untorn reads; it does not prevent a maintenance retirement and an interactive supersede from each reading version 1 and the second silently clobbering the first.
- **Writes are atomic and crash-safe**, so a concurrent reader sees the old file or the new one, never a partial one. The write recipe is in DECISIONS.md.
- **The interception path takes no lock.** It opens the projection and reads through the descriptor, so a rename underneath it leaves it reading the previous inode intact. This matters for D1: a read lock would put an unbounded wait inside a 50 ms budget.
- **One lock order, globally**: catalog before operational state, always. Graduation crosses both tiers, so the entry card is the single commit point and the confirmation counter is a hint that can be recomputed from decision records. That removes the half-applied state where the counter reaches three and the card is still probationary.
- **Operational state** allows many concurrent readers and one writer.
- **The fifth writer is the sync daemon.** The catalog may sit in a synced folder, sync daemons replace files underneath in-progress operations, and they honour no advisory lock. So the catalog tolerates an uncooperative external writer: the version compare-and-swap detects the clobber, and a card that changed underneath is treated as a conflict to reconcile rather than an error. Operational state and projections are never synced, which is what keeps the database files safe.

**Storage has three tiers.**

| Tier | Contents | Rebuildable | Location |
|---|---|---|---|
| Source of truth | Entry cards, markdown | No | Catalog, may be synced |
| Operational state | Review queue, decision records, confirmation counters, verdict cache, cost ledger, telemetry, gate instrumentation | No | Local disk only |
| Projections | Check cache, search index | Yes, and the rebuild is exercised in tests | Local disk only |

Operational state exists because the middle tier is neither source of truth nor derivable, and calling it a projection would make the rebuild fitness function false.

**The source of truth is markdown cards, and this is a scale decision.** At a few hundred entries the corpus is folded in memory, so contradiction, subsumption, and retrieval never need a database engine; the only structured store is a disposable local index. What the truth substrate must earn instead is legibility for the review gate, hand-editing in Obsidian, a diffable lifecycle history, and a near-identity render to the host commit targets, which are markdown regardless. Cards win all four, and git supplies the transaction-time history for free. A database of record, an event-sourcing engine, or a sync-CRDT would each solve a scale, provenance, or multi-device-merge problem this corpus does not have, at the cost of the legibility it does. DECISIONS.md records the full comparison.

**A card's frontmatter is a validated typed contract.** The typed fields (scope, condition, validity, provenance, enforcement tier) are checked against a versioned schema on every read and write, not treated as freeform YAML. The prose body is the human-facing content; the frontmatter is the machine contract the projections are folded from.

**Provenance is a shape, not a field.** Every enforced decision and every committed entry resolves to the evidence it came from, the gate it passed, and the basis it was decided against. That is what the four separate record layers in 6.1 exist to make possible, and it is why none of them may be collapsed for convenience [N6].

**Validity is bi-temporal, split across the card and git.** Valid-time, when a preference or fact holds and when its condition stops holding, is explicit frontmatter. Transaction-time, when an entry was recorded, changed, or superseded, is the card's git history. Currency is invalidate-not-delete: retire and supersede set a status and keep the card, recoverable from git; only a removal on request [R1.16] hard-deletes. This carries R1.9, R1.10, R2.3, R2.8, R2.9, R2.10, and makes N8's two grains fall out of the model: a retired entry is a status change plus git, a removed one is a deleted file.

**Writes stay inside owned regions.** Every target the host reads is written only within a region Precept owns, so text authored outside it survives both the write and the uninstall [N8].

**Format is versioned from the first entry.** The card frontmatter schema and the operational database each carry a version. Additive changes migrate forward through a versioned, transactional migration chain, so a failed migration is retryable, not half-applied. A card whose frontmatter is a newer major version is refused, not opened, because the alternative is silent destruction on the next write [N12].

**Cost and quota.** Inference competes with the user's own quota, so: spend is attributed per flow at the call site [N10]; a per-period budget throttles the learning loop; crossing a threshold raises an alert; and one control disables learning entirely while leaving enforcement of existing entries running [Risk 5, N4]. One caveat the requirement does not state: per-call token accounting is returned by the metered API and not by subscription-mediated invocation, so under the subscription backend attribution degrades to call counts and estimated sizes. N10's fidelity is a function of which backend `infer` uses, and the diagnostic says which is active.

**Error budget.** Fail-open plus a record means a fully broken Precept behaves like a healthy one. A failure rate above a threshold, counted in operational state, surfaces as a degraded-mode warning at session start. Without this, D2's justification is unfalsifiable.

**Break-glass.** Claude Code must be able to disable Precept without Precept's cooperation. Hooks are not permission-gated, so a deny rule does not reach them: the mechanism is overriding the `hooks` block at a higher-precedence settings scope, which the documented precedence order makes deterministic, and which works when Precept's own state is the corrupted thing. A per-entry disable covers the ordinary case. A fitness function exercises both.

**Three thresholds are left unset**, for the same reason the README leaves two KPI targets blank: the false-block bound [N13], the error-budget failure rate, and the cost alert level each need a usage baseline that does not exist yet. They are named here as required settings with no default, not filled with a guess, and the diagnostic reports them as unset.

**Two planes.** The repository holds the engine and synthetic cases; learned content lives outside it, and CI fails the build if a populated entry, local session config, or personal marker is ever tracked [N11].

## 8. Implementation decisions

Reasoning belongs in [DECISIONS.md](DECISIONS.md); recorded here in brief.

| Decision | Choice | Why |
|---|---|---|
| Hook distribution | Bundle the hot entrypoints to one dependency-free script; do not compile them | Measured on the target machine, a compiled binary starts about 1.7x slower than the script (42 ms against 26 ms), so compiling costs the budget it was meant to protect. Bundling without compiling keeps the 26 ms startup and removes the dependency tree entirely, which is the dependency drift this project has hit; hooks run with the session's cwd, so relative module resolution is hostile. Pinning an absolute interpreter path fixes PATH variance but not an in-place runtime upgrade and not machine portability, since that path is machine-specific state written into a synced settings file. So: bundle the hooks, compile the command line, and have the startup diagnostic verify the pinned interpreter still exists |
| Hot-path validation | None. Hand-written narrowing over the host's JSON | A schema library import costs more than the entire runtime startup. Model output still gets full validation inside `infer`, where a network call dominates |
| Process model | Spawn per call; a warm local daemon is a costed escape hatch | Spawn has no lifecycle, staleness, or version-skew problem. The floor is 26 ms, and prepared-statement caching never pays under spawn. If the D1 budget fails, a hook fronting a loopback daemon is the answer, since the pause is a warm process rather than a cold spawn. Revisit on the budget test, not on assumption |
| Package layout | One package, several entrypoints | One dependency set, one release cadence, one owner |
| Retrieval | Full-text search, no embeddings today | Measured at 0.8 ms over 500 documents. Separately, `loadExtension` throws under Bun's SQLite on macOS, so the usual vector extension needs a custom SQLite build shipped alongside; if a dense arm is ever added, brute-force similarity over a few hundred vectors in plain TypeScript avoids the extension entirely |
| Rewrite decisions | Kept; a live field collision applies no rewrite | Rewrite corrects a bad call in place instead of denying and retrying it. It is the only outcome carrying data, so the only threat to order independence. The runtime rule, one field touched by two rewrites means no rewrite, recovers commutativity unconditionally without giving up the capability; authoring-time collision flagging over history is an advisory layer on top |

## 9. Fitness functions

Architectural properties rot silently unless they are executable. Each row is a test.

| Property | Check | Driver |
|---|---|---|
| The hot path stays thin | Dependency rule: the interception path may not import `infer`, `gate`, `retrieve`, or a schema library | D1 |
| Startup within budget | Timed run of the interception entrypoint against the 50 ms and 120 ms figures | D1, N2 |
| Faults allow and record | Fault injection at each seam | D2, N1 |
| Check validation stays in budget | The evidence-scan validators (reachable, contradicts, subsumes) run over the golden entry set within their time bound on any language change | D3, 5.1 |
| Nothing claims what it cannot do | Construction-time test that a blocking tier cannot attach to an unenforceable entry | D3, N5 |
| Probation holds | A probationary entry emits only `ask`, never `deny` or `rewrite` | R1.19-R1.21 |
| Rewrites commute | A field targeted by more than one applicable rewrite is left unrewritten and recorded; authoring flags a historical field collision | 6.4 |
| Both context budgets hold | Retrieval over a catalog an order of magnitude larger than the real one; and the always-loaded contribution against its line cap | D4, N9, R1.8 |
| Nothing reaches enforcement unreviewed | The write path structurally requires a decision record | D5, N7 |
| Inference abstains and corroborates | A labelled evidence set: ambiguous windows yield no candidate, and repeated observations from one cause do not clear the corroboration bar while independent ones do | R1.2, Risk 1 |
| Hindsight recovers misses | The sampled re-examination, run at a lower threshold over a labelled slice, recovers seeded preferences the live detector was tuned to miss | R1.14 |
| The gate still works | Known-bad candidates seeded into the queue at intervals; the approval rate on them is the measure | D5 |
| Verdicts are stable | Caching by fact-record hash makes a repeated situation identical by construction; the measured property is agreement across repeated samples on novel records, reported with its spread, plus false-block rate against its bound | N13 |
| Enforcement quality | Deterministic confusion matrix over the golden set, CI-gated | KPI |
| Behaviour actually changes | Paired before and after with a bootstrap confidence interval, run off CI | KPI, O1 |
| Projections rebuild | Delete and rebuild each, asserting equivalence | Section 7 |
| Migrations chain | Every version pair migrates forward without loss | N12 |
| Host contract holds | Recorded event fixtures replayed against `host`; live-fire a known block through the real host on version change | Constraint 2 |
| Nothing private is tracked | Repository scan | N11 |

**Testing posture.** The model client is injected at one seam, so the whole suite runs offline against a fake. Host fixtures are a recorded corpus, which is the primary detector for the highest-volatility risk in this document. Tests are hermetic: each supplies its own catalog, state, and host directories, and reads no real machine state.

## 10. Delivery, cold start, and migration

**This is a rebuild of a working system, so it is sequenced as a strangler, not a big bang.** The architecture's own invariant makes that possible: the markdown cards are the source of truth and are language-agnostic, so a TypeScript module and the existing Python module operate on the same catalog. They coordinate the way section 7 handles any second writer, by version compare-and-swap on each card, not by a shared lock across runtimes. Operational state is the constraint: its queue, counters, and ledgers are single-owner per seam, opened by exactly one runtime at a time and handed over when that seam migrates, never concurrently opened by both, so the newer-major refusal rule in section 7 cannot strand the trailing runtime. The rebuild replaces one seam at a time behind the shared catalog, never by a flag day, and a working system exists at every step.

The order is set by value per session, not by the dependency graph.

1. **Knowledge first (O2).** A saved fact pays off the first time it is retrieved, in the very next session. This is the half that makes an empty catalog stop being pure overhead soonest, and it needs no enforcement machinery: capture, review, store, retrieve, inject. Build the observation, inference, gate, store, and retrieve seams for knowledge, in TypeScript, reading and writing the shared catalog.
2. **The hot path.** The interception and guard entrypoints are the smallest self-contained piece and the one place Bun's startup actually earns the migration, so they move next. Enforcement of already-authored rules is deterministic and needs no model, so this seam can be validated in isolation.
3. **Preferences and enforcement authoring (O1).** The check language, the probation lifecycle, and the write path for blocking entries. This is the heaviest seam and it is last, because it depends on accumulated corrections to be worth anything and on the hot path to run against.

From a cold start, enforcement is the last half to deliver value, so it is sequenced last, even though it is the half that already exists in Python.

**Empty catalog.** Until sessions accumulate, a bootstrap pass seeds the catalog from the user's existing setup, imported as entries marked by origin so they are never re-emitted back to their source. Knowledge-first sequencing is the other half of this answer: it shortens the interval during which Precept costs more than it returns.

**From the Python implementation.** Existing cards, knowledge notes, approval history, and telemetry are exactly the accumulated state N12 exists to protect. Because the strangler has both implementations reading the same cards, card migration is continuous rather than a cutover: the schema version on each card governs, and a card written by either implementation is readable by the other at the same major version. Operational state (queue, counters, ledgers) is migrated by an explicit one-time importer with a verification pass when its owning seam moves, not by the ordinary migration chain.

## 11. Risks in this architecture

Distinct from the product risks in the README. These are ways the structure itself fails.

**The check language is too narrow to matter.** If most real corrections cannot be expressed in it, the deterministic tier stays empty and the system is all guidance. The opposite failure is a language that grows one operator per unexpressible correction until it is an ad-hoc programming language. The grammar is deliberately closed against that: new expressiveness enters as code-authored structural predicates with test examples, not as new logic, and the validators stay a corpus scan rather than a proof, so widening the language cannot silently break them.

**The review gate degrades into a rubber stamp.** An adjacent measurement: Claude Code users approve roughly 93% of permission prompts, and the auto-approve rate climbs with tenure. That gate is not this one, since it interrupts in the moment on a single action with a visible cost of denial, where this one is an asynchronous review of a proposed standing rule. So the figure is suggestive, not direct evidence. The supporting research is more transferable: density of prompts per unit of context drives override rather than lifetime volume, and showing a rationale beside an approve button raises acceptance of wrong items as much as right ones. The architecture's answers: cap review density and let the excess age in the queue; make correction the primary action, not approval; and measure the gate with seeded known-bad candidates instead of asserting it works.

Verification of claims checkable against the repository needs care, because the obvious form of it reintroduces the hazard. A verification badge next to an approve button is a rationale next to an approve button, and a verification result is the most persuasive rationale available. So the order is inverted: the reviewer states the scope the entry should hold under before the verification result is revealed. That is the cognitive-forcing shape the research supports, it is disliked by users in exactly the studies that show it works, and verification never substitutes for the decision record, which N7 makes absolute.

**The host contract moves and the break is silent.** Fail-open means a contract change downgrades an entry to a no-op with no error. `host` confines the damage and the failure record makes it visible, but only the fixture replay and live-fire checks in section 9 detect it.

**Evidence-based validation misses what history has not shown.** Validating a check against recorded traffic instead of proving it means a contradiction or a redundancy between two checks that never co-occurred is not caught at authoring time. (Reachability is not in this gap: a check with no historical match is validated by a reviewed example instead, per 5.1.) This is a deliberate trade of soundness for a system that ships, and it is defensible only because the runtime rules absorb what validation misses: a false or conflicting check fails toward not enforcing (D2), a colliding rewrite applies nothing (6.4), and the sampled hindsight audit (6.5) is the backstop that surfaces a bad rule the gate let through. The residual exposure is a rule that is wrong in a way that never fires wrongly, which by construction costs nothing until it does, at which point the failure record names it.

**The two-language split is a second thing to maintain.** A blocking check and a steering note are authored, stored, and validated differently, which is real overhead. It is justified only while the deterministic tier carries enough rules to matter. If almost every correction ends up as guidance, the split is cost without return, and the right response then is to collapse it, not keep it for elegance.

## 12. Where to start reading

1. Sections 6.1 and 6.2, the write path and inference: the loop the product is actually about, and where the primary objective lives.
2. Section 5.1, the check language and why it is validated against history rather than proved: the core choice on the enforcement side.
3. `domain`: the entry model and the invariants it holds.
4. `host`: the contract, and the one place a host change lands.
