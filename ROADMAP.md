# Roadmap

Precept runs the full loop end to end today, installed and self-running; the planned work deepens and hardens it rather than completing a missing half. The design for each item is in [ARCHITECTURE.md](ARCHITECTURE.md) and [DECISIONS.md](DECISIONS.md); build status is in [ts/STATUS.md](ts/STATUS.md).

## Built

The whole spine of both objectives, end to end, offline-tested and installed as the live hooks.

- **Observe.** Installed as the Claude Code hooks (`install` and `uninstall`, an exact inverse). Each finished session's transcript becomes evidence: a verbatim window per human-typed turn behind the provenance gate, and a silent-edit diff of the agent's output against the file's final state (R1.1).
- **Infer.** A cost-gated model backend (`claude -p`) proposes at most one durable item per evidence window or abstains (R1.2); a plain task turn spends no call. On SessionEnd the loop runs itself in the background when the backend is enabled.
- **Review and record.** Nothing reaches the catalog except through the human gate, and every decision is an immutable record that retains the proposed-and-committed delta (N6, N7). Only a user-typed turn may source a blocking entry.
- **Store and retrieve.** Governed markdown cards under a versioned frontmatter contract; full-text retrieval, validity-filtered and budgeted, injected per prompt as the relevant slice (O2).
- **Enforce.** Live hard rules compile to a plain-JSON check cache the interception hook reads and evaluates deterministically, as deny, ask, or allow, failing open and recording faults (N1). No model, parser, or schema library runs on the hot path, held by a fitness function. A new rule is probationary until three confirmations graduate it (R1.19-R1.21).
- **Keep current.** Retire and supersede transitions that invalidate rather than delete, and review-time surfacing of a near-duplicate to reconcile (R1.4).

## Planned

None of the below is required for the loop to run. They deepen the learning half, add the judgment tier that is deferred by design, and harden, optimize, and measure the system. Each is mapped to the requirement it serves or the risk it mitigates.

### Learning loop (O1, O2)

- **Currency sweep, part 2** (R1.9, R1.11, R1.12). An off-turn `maintain` pass that expires an entry past its `validUntil`, resets an operational hard rule to probationary when recorded history shows its check matched a call that still executed, and reports a rule whose check a live rule subsumes. Part 1 (the retire and supersede transitions, review-time duplicate surfacing) is built; the rest is designed in DECISIONS.md.
- **Inference correction from deltas** (R1.13). Every decision records the delta between what was proposed and what was committed, and nothing consumes it. Fold it back into inference, so a similar correction becomes an exemplar for the next inference, a repeated correction a standing rule on the inference step, and the keep and dismiss record calibrates scope.
- **Hindsight audit** (R1.14). A scheduled, lower-threshold pass over retained evidence that recovers a preference the live detector missed and calibrates detection. Evidence is retained append-only for exactly this; the pass is unbuilt.

### Enforcement

- **Turn-end judgment tier** (R1.18, N13). A `Stop` entrypoint for structural checks, a parser kept off the hot path, and the model-verdict tier for a requirement no mechanical check can express. Deferred by design.
- **Check synthesis from a correction** (R1.17). A hard rule commits only when the model supplies a check, so a model-proposed rule lands as guidance. Synthesizing the check from the correction moves more of the must-hold few onto the deterministic tier.
- **Input-rewrite outcome** (ARCHITECTURE 6.4). The engine is deny, ask, and allow; the rewrite outcome is designed and not built.

### Placement and injection

- **Convention writer** (R1.7, R1.8). A convention loads through Precept's injected context rather than the host's own scoping. Write it into `.claude/rules/`, under an always-on line cap, so it loads by the mechanism its type calls for.
- **SessionStart injection** (R1.8). A no-op until the bounded always-on set exists.
- **Per-tool hook narrowing** (ARCHITECTURE 5.4). Install registers PreToolUse on the `*` matcher, so interception spawns on every tool call. Registering only the tools a rule references, regenerated on `compile`, is what makes most turns invoke Precept zero times.

### Knowledge (O2)

- **Vault integration.** Governed knowledge lives as catalog cards and injects per prompt, which is the O2 mechanism. Filing into the Obsidian vault is not carried into the rebuild; revisit it, behind the same review gate, if vault-native knowledge that is browsable and wikilinked is wanted.

### Durability

- **Write-path compare-and-swap** (ARCHITECTURE 7). Only the lifecycle read-modify-write bumps `version` under the card lock; `writeCard` does a plain atomic rename. The per-card CAS closes the window where two writers clobber.
- **Git as transaction-time** (ARCHITECTURE 7). The bi-temporal model names git history as transaction-time; asserted, not yet read by code.

### Measurement

- **Enforcement-quality eval.** A confusion-matrix gate over a golden set of checks and calls. CI runs the dependency-rule, interception, and behavior suites; this quality gate is not yet ported.
- **Cost and latency metering** (Risk 5). Measure the loop's token spend and its added delay and alert on a threshold, so a step that grows too expensive surfaces before it is set aside.
- **Install health and contract drift** (ARCHITECTURE 11). A check that the wired hooks still fire and still block, so a silent change to the host contract surfaces instead of degrading a rule to a no-op, plus a cold-start pass that seeds an initial catalog from the existing setup.
