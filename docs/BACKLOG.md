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

### A. `rewrite` is the default for substitution corrections
When a correction is a clean substitution ("use X not Y", Y -> X in the same tool field),
synthesize a `rewrite` policy (decision=rewrite, rewrite_to={field: corrected value}) by
DEFAULT, not deny. Deny only when there is no clean substitution. enforce + models already
support rewrite; the change is in `synthesize.py` (prefer rewrite for substitutions).

### B. Compile clean bans to native `permissions.deny`
For clean tool+path/domain bans that need NO argument logic (`Read(.env)`, `WebFetch(domain:..)`,
whole-tool bans), compile to a `permissions.deny` entry in settings.json instead of a
PreToolUse hook. Auto-pick by shape: clean ban -> permission rule; command-argument logic
(regex on a Bash command) -> hook (permission Bash-arg patterns are bypassable, per CC docs).
Touches: `synthesize.py` (classify shape), `install.py`/`compile.py` (write a marker-managed
permissions block), enforce unchanged (CC enforces permission rules natively).

### C. Scope-aware enforcement, default GLOBAL
Rules fire only within their scope, using the event's `cwd` (and detected language). DEFAULT
scope = **global** (fires everywhere) unless the correction specifies narrower (this repo /
this language). repo-scope stores the repo root; fire only when cwd is inside it. Touches:
`models.py` (a scope_value alongside the Scope enum), `enforce.py` (filter by cwd before
matching), `compile.py` (carry scope into policies.json), `detect.py`/`synthesize.py` (set
scope; default global).

### D. UserPromptSubmit rules (third hard surface)
Add UserPromptSubmit as a prompt-time rule surface (e.g. "always include the ticket id").
It can block+erase the prompt with a reason, or inject `additionalContext`. Touches:
`hooks.py` (new `precept-hook-userpromptsubmit`), `install.py` (register it), `enforce.py`
(`evaluate_userpromptsubmit`), `adapters/claude_code.py` (its wire shape), `synthesize.py`
(target it for prompt-time corrections). HookEvent.USER_PROMPT_SUBMIT already exists.

## Follow-ups from the Stop-verdict build (non-blocking)
- **Wire `applies_when` synthesis into `_judgment_policy`.** #5's relevance gate is
  plumbed end-to-end in enforce + the deterministic synthesizer path, but the direct
  judgment-compile path (`synthesize._judgment_policy`) sets `applies_when=None`, so a
  judgment lesson ("no stub code") never gets the free relevance-skip in production yet.
  Synthesize a sensible gate (e.g. "no stub code" -> applies_when Edit/Write).
- **Validator note:** `applies_when` is silently ignored on non-judgment policies; add a
  light validator (set only on JUDGMENT) for honesty.

## Done
- **Stop-verdict layer (#4 + #5 core), 2026-06-29.** AI-based claim detection (regex
  retired), judgment relevance-gate plumbing, and ONE consolidated verdict call per turn
  at Stop, with the `verdict_fn` injection seam keeping the Tier-1 eval deterministic.
  Fail-open intact; hot path stays stdlib. 56 tests, evals green. (Built by a background
  plan->implement->test->review pipeline; reviewer verdict: ship.)
