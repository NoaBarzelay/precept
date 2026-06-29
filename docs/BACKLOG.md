# Backlog: improvements & changes

A running list of refinements raised during review. We resume these after the
current review pass. Newest items go under "Open"; move to "Done" when shipped.

## Open

### 1. Incremental, on-the-fly detection (cursor + pre-filter)
**Why.** Detection already runs on every Stop (per turn, so it is responsive even in a
days-long session). But each Stop spawns a fresh `detect` that re-reads the transcript
tail and makes a Haiku call, so a long session = hundreds of redundant LLM calls
re-examining the same or irrelevant turns. Dedup-by-id stops duplicate cards but not the
wasted calls or re-processing.

**Fix (the locked "two-phase: cursor-mark on Stop + batched classify").**
- Per-session **cursor**: a small file in the state dir recording the last transcript
  offset already processed; on each Stop, classify only the NEW turns, then advance it.
- Near-free **regex pre-filter** on the new user turns (cues: `no` / `don't` / `never` /
  `actually` / `stop` / "use X not Y" / `should have` / `again`); only call Haiku when a
  correction is actually likely. This is what keeps per-turn detection cheap.
- Small per-session **lock** so two Stop events firing close together don't double-classify
  the same turns (makes detection idempotent; fixes a latent double-spawn bug).

**Outcome.** Same per-turn responsiveness, cheap on long sessions, nothing re-processed.
**Touches.** `detect.py` (cursor + pre-filter), `hooks.py` (pass session_id through),
`paths.py` (cursor path). Cards stay PENDING, review model unchanged.
**Note.** The pre-filter regex here is only a cost gate (recall-biased: decides *whether*
to spend an LLM call), not a semantic classifier. The actual correction classification is
still the LLM. (Distinct from #4, where the *semantic decision* must be AI, not regex.)
Revisit if we want the pre-filter AI-based too.

### 2. Robust hook command paths (install)
**Why.** `install` writes bare command names (`precept-hook-pretooluse`); if Precept lives
in a virtualenv not on Claude Code's PATH, the hook silently does not run.
**Fix.** Write the absolute path to each console-script into `settings.json`; add a
`precept doctor` check that the hook commands are reachable and that settings.json
actually points at them.
**Touches.** `install.py`, `cli.py` (doctor).

### 3. Proactive review (ask at detection time, no command needed)
**Why.** Today a detected rule lands as a PENDING card you have to *discover* (`precept
list` / `why`) and approve (`precept keep`). You want Precept to surface a new rule right
away and ask "is this good enough, keep it?" in the flow, not make you remember a command.

**Design constraint to resolve.** Claude Code hooks cannot render a native yes/no to the
human. Realistic mechanisms (pick/combine):
- Surface the drafted rule immediately via the Stop hook's `additionalContext` (and/or a
  SessionStart / UserPromptSubmit injection): in-session you see "I drafted a rule from
  your correction: <summary>. Keep it?" and can approve conversationally; Precept (or
  Claude) then runs the keep.
- A one-tap confirm surfaced for you (`precept keep`/`skip <id>`), or later an MCP `review`
  tool / a small TUI inbox that pops pending items.
- Keep the PENDING gate intact (never auto-enforce): this changes HOW you're asked
  (proactive, in-flow) not WHETHER you approve.
**Touches.** `hooks.py` (surface via `additionalContext`), `detect.py` (flag "needs
review"), possibly a SessionStart/UserPromptSubmit hook + its install entry.

### 4. AI-based claim / completion detection (trajectory rules) — NOT regex
**Decision (Noa 2026-06-29): claim detection must be AI-based, not regex.**
**Why.** A trajectory rule decides "is the agent claiming success?" via a brittle regex
(`claim_pattern`): false positives ("not done yet" contains "done"), false negatives
("shipped it", "ready to merge"), English-only, phrasing-dependent.
**Fix.** Replace the `claim_pattern` regex with an AI verdict ("is the final message
claiming the task is complete?"). The deterministic half of a trajectory rule stays
cheap and transcript-based (did the required tool call happen?); only the claim judgment
goes to the model.
**Schema.** `TrajectorySpec.claim_pattern` (regex) deprecated; the claim is judged by AI.
Keep `requires` (a `Match`) deterministic.
**Converges with #5.** This claim verdict is folded into the single consolidated Stop
verdict call, not a separate call per trajectory rule.
**Touches.** `enforce.py` (evaluate_stop), `judge.py` (claim verdict), `synthesize.py`
(stop emitting a claim regex), `models.py` (`TrajectorySpec`).

### 5. Judgment-rule scoping + a single batched verdict at Stop
**Why.** Every active judgment rule currently makes its own Haiku call on every Stop
(N rules = N calls per turn, most irrelevant, e.g. checking "no stub code" on a turn that
wrote no code). Does not scale as standing standards ("all my requests") accumulate.
**Fix.**
- **Relevance gate:** each judgment rule gets a cheap deterministic `applies_when`
  condition over the turn's activity ("no stub code" only if an Edit/Write happened;
  "cite sources" only if a factual answer was given). Irrelevant rules are skipped for
  free (no model call).
- **Batch:** evaluate all relevant Stop-time AI verdicts (judgment standards AND the
  AI claim detections from #4) in ONE consolidated model call per turn ("check these K
  standards against the final state; return any clearly violated"). Block on the first
  violation. Bias toward not-blocking (false block is the costly error).
**Outcome.** Many persistent judgment rules stay cheap: at most one Stop verdict call per
turn, only when something relevant happened.
**Touches.** `models.py` (`Policy.applies_when`), `enforce.py` (gate + batch),
`judge.py` (consolidated-verdict schema).

> **#4 + #5 share one mechanism:** a single consolidated Stop AI verdict call that handles
> both "is the agent claiming success" (trajectory) and "are the standards met" (judgment).

### 6. Rule governance: decay / supersede / conflict-detection  (deferred, Noa 2026-06-29)
Part of the self-improvement pillar; deferred but captured so it's not missed.
- **decay:** archive rules that never fire (fire_count stays 0 past a threshold), proposed
  for retirement.
- **supersede:** a newer rule replaces an older one (old marked archived).
- **conflict-detection:** detect two rules that contradict (the expensive LLM-judge piece).

---

## Decided rule work — queued for the NEXT background build (after the Stop-verdict build lands)
Owner decisions, 2026-06-29. Build these as a second multi-agent pipeline once
wu9mkvty7 (the #4/#5 Stop-verdict build) is merged, to avoid two agents editing the same
files concurrently.

### A. `rewrite` is the default for substitution corrections — DONE (2026-06-29)
The synthesizer SYSTEM prompt now PREFERS rewrite for a clean whole-field substitution
("use pnpm not npm" -> decision=rewrite, rewrite_to={field: corrected value}) and reserves
deny for destructive ops and variadic commands where a blind whole-field replace would
drop arguments. The model validator already fail-closes a REWRITE draft with no rewrite_to.
New deterministic eval cases assert the rewrite payload (harness extended with
`expect_rewrite`, counted as a correctly-handled allow). Deferred: a field-level
token-substitution rewrite_to shape (regex-replace within a variadic field) so a token swap
inside `npm install left-pad` can rewrite rather than deny.

### B. Compile clean bans to native `permissions.deny` — DONE (2026-06-29)
A clean tool+path/domain/whole-tool ban now compiles to a settings.json permission entry
instead of a hook. `synthesize._as_permission_rule` classifies by SHAPE (deterministic, not
LLM-chosen): clean `Read/Edit/Write/Glob/Grep` path glob/equals/starts_with -> `Tool(spec)`;
`WebFetch` host -> `WebFetch(domain:host)`; empty conditions -> bare tool; a Bash-arg or
regex-path ban -> None (stays a hook, since CC ignores Bash arg-patterns and a regex->gitignore
translation is unsafe). A `permission_rule` policy is routed to settings.json by `compile_all`
and EXCLUDED from the hook cache, so `enforce.py` is literally unchanged. `install` syncs a
marker-managed permissions block via a sidecar manifest in the state dir (idempotent, atomic,
.bak; subtracts only Precept's own prior strings, never the user's; uninstall is an exact
inverse). Bootstrap is intentionally left unchanged (imported rules stay hooks — Precept never
adopts the user's pre-existing permission entries). VERIFIED live: permissions schema
(deny/ask/allow, `Tool(specifier)`, `WebFetch(domain:)`, gitignore path semantics, and the
`Bash(command:...)`-is-ignored warning) against code.claude.com/docs/en/permissions.

### C. Scope-aware enforcement, default GLOBAL — DONE (2026-06-29)
Rules fire only within their scope, using the event's `cwd`. DEFAULT scope = **global**
(fires everywhere) unless narrower. `models.py` carries `scope`+`scope_value` on Policy
(and Lesson); `enforce._in_scope` filters every candidate list by cwd before matching
(repo: cwd at/under the stored root; a repo rule with no usable cwd is SKIPPED — narrower,
never wider); `compile.py` carries scope/scope_value and skips a repo rule with no root;
`detect.py` resolves the repo root from the session cwd via `_git_root` and falls back to
global when it can't. Deferred: real LANGUAGE-scope matching (plumbed as global-for-now
with an inline TODO — would read package.json/pyproject from cwd in the hot path).

### D. UserPromptSubmit rules (third hard surface) — DONE (2026-06-29)
A prompt-time rule surface ("always include the ticket id"). `evaluate_userpromptsubmit`
runs deterministic single_call rules over a synthetic `prompt` field (a presence-required
rule uses op=not_regex so it fires exactly when the required content is absent) then a
consolidated judgment verdict (same seam as Stop), scope-filtered by cwd, FAIL-OPEN (a
None/empty verdict never erases the user's prompt). New `precept-hook-userpromptsubmit`
entrypoint + console script; install registers it (uninstall covered by the existing
prefix-keyed strip); adapter wire fns (block / additionalContext / allow). VERIFIED live:
the UserPromptSubmit contract (stdin cwd/prompt; `{"decision":"block","reason"}` blocks +
erases; `hookSpecificOutput.additionalContext` injects) against code.claude.com/docs/en/hooks.

## Follow-ups from the Stop-verdict build
- **DONE (item 0, 2026-06-29).** `synthesize._judgment_policy` now infers a relevance
  gate via `_infer_applies_when` (a code-quality lesson -> `applies_when` Edit), so the
  free relevance-skip fires in production; and `Policy` now validates that `applies_when`
  is only set on JUDGMENT (fail-closed at compile, never at enforce).
  *Deferred follow-up:* OR-of-tools `applies_when` (Edit OR Write) is a schema change;
  today the gate targets Edit (the dominant code-mutation tool).

## Done
- **Stop-verdict layer (#4 + #5 core), 2026-06-29.** AI-based claim detection (regex
  retired), judgment relevance-gate plumbing, and ONE consolidated verdict call per turn
  at Stop, with the `verdict_fn` injection seam keeping the Tier-1 eval deterministic.
  Fail-open intact; hot path stays stdlib. 56 tests, evals green. (Built by a background
  plan->implement->test->review pipeline; reviewer verdict: ship.)
