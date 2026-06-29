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

## Done
(none yet)
