# Backlog: improvements & changes

A running list of refinements raised during review. We resume these after the
current review pass. Newest items go under "Open"; move to "Done" when shipped.

## Open

> **Items 1, 2, 3, 6 — DONE (2026-06-30).** Built as a background pipeline; see the "Done"
> section at the bottom for the shipped summary. Entries kept here for the original spec.

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

### 7. Knowledge pillar (slice 2 + ops) — DONE (2026-06-30)
Slice 1 (index + FTS5 search + convention suggester + integrity auditor/renamer) was the
first background build. Slice 2 (capture + retire-notes-silo + retrieval-injection + daily
audit/throttle + ANN-watch seam) shipped 2026-06-30 — see the "Done" section at the bottom.
Original spec retained below.

Remaining at the time:
- **Capture** rides the per-turn detect pass (auto-write + auto-route to the right folder +
  confirm); retire any `~/.precept/notes` silo. Entities = folders, relationships = wikilinks.
- **Retrieval injection** at SessionStart + UserPromptSubmit (BM25 first; local embeddings +
  sqlite-vec `vectors` table deferred, local model only so knowledge never leaves the machine).
- **Daily integrity audit** (scheduled): re-runs the auditor, surfaces rename/placement/
  missing-frontmatter/unfiled-knowledge proposals as PENDING (block/propose, never silent).
  - **ANN watch (Noa 2026-06-30):** the daily audit also watches the `vectors` table size.
    Nearest-neighbor is brute-force (fine to ~tens of thousands of vectors). When the count
    crosses the threshold where brute-force scan gets slow (~1M), the audit SUGGESTS
    implementing an ANN graph index (HNSW). Suggestion only, surfaced like any other finding.

### 6. Rule governance: decay / supersede / conflict-detection  (deferred, Noa 2026-06-29)
Part of the self-improvement pillar; deferred but captured so it's not missed.
- **decay:** archive rules that never fire (fire_count stays 0 past a threshold), proposed
  for retirement.
- **supersede:** a newer rule replaces an older one (old marked archived).
- **conflict-detection:** detect two rules that contradict (the expensive LLM-judge piece).

### 8. Hardcoded vs flexible-AI audit of the whole platform infra (Noa, 2026-06-30)
**Why.** The single most load-bearing design axis in Precept is *which seams are
deterministic/hardcoded vs which are flexible LLM calls*. It's been decided ad hoc per
feature (DETECT=AI, ENFORCE matcher=stdlib, the gate=deterministic + LLM verdict, the
pre-filter=regex-cost-gate-not-classifier, conflict-detection=LLM-judge). Noa wants a
deliberate, platform-wide pass instead of case-by-case.
**Do.** Enumerate every seam that currently makes (or could make) that choice — DETECT,
COMPILE/synthesize, the Stop/judgment verdict, the consolidated verdict, conflict-detection,
the detect pre-filter, convention relevance-injection, knowledge retrieval (keyword vs
vector), routing among soft homes — and for each decide: hardcoded, AI, or AI-gated-by-a-
deterministic-frame, with the *reason* (precision/cost/capability) written down. Cross-check
against the existing principle scattered in the routing + gate-decision notes (see
[[project precept platform]]): hardness = "is there a worthwhile deterministic GATE," and
the verdict AT the gate may be deterministic OR an LLM call. Output = one doc (e.g.
docs/DETERMINISM-MAP.md) that becomes the reference the multi-way router is built against.
**Note.** #4 (pre-filter must stay a cost gate, semantic decision stays AI) and #5 are
specific instances of this question; this item is the systematic version.

### 9. Token-eval follow-ups (Noa, 2026-06-30)
From building the token-consumption eval (branch `feat/token-eval`):
- **Subscription-native view.** The eval frames tokens as the unit and $ as notional (correct
  for the Claude Code subscription). Next: show usage against the actual subscription
  quota / rate-limit window if/when that signal is reachable, not just raw token totals.
- **Meter growth bound.** `token_usage.jsonl` is append-only and unbounded (one line per LLM
  call). Light for now (~150 B/line, fail-open, no API call at record time), but add cheap
  rotation/size-cap or periodic roll-up so it can't grow without limit over months.
- **count_tokens needs a metered key.** `--static --refresh-baseline` (5 count_tokens calls)
  can't run on the subscription/OAuth token headlessly, so the committed baseline stays `{}`
  and the static ledger uses the offline estimate. Revisit if an exact baseline is wanted
  (run once from an env with an API key, commit the snapshot).

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
- **Item 7 — Knowledge pillar slice 2, 2026-06-30.** Built by a background pipeline.
  - **Capture.** `knowledge/capture.py` rides the per-turn DETECT pass (off Stop) over the
    SAME provenance-filtered user turns. A recall-biased regex pre-filter (cost gate) gates a
    schema-constrained `MaybeKnowledge` LLM call (fail-CLOSED/abstain). Durable knowledge is
    written as a well-formed `type: knowledge` vault file (frontmatter `updated:` + `##
    Sources`), AUTO-ROUTED to the best existing folder via `index.route_folder` (content-word
    BM25 OR-match; a clearly-novel topic lands in a new `Notes/` folder instead of a forced
    fit), and marked PENDING (`precept_status: pending`) — surfaced for confirmation, never
    silently final. Entirely fail-OPEN (no vault / any error -> no-op).
  - **Retire the notes silo.** `knowledge.add/search/reindex` (the `precept note/recall/
    reindex` CLI) now read/write the SAME vault-backed knowledge index — ONE knowledge store.
    `~/.precept/notes` is gone; `knowledge/store.py` is the shared filer (render + route +
    incremental `index.upsert_file`). `test_knowledge.py` updated to the vault fixture.
  - **Retrieval injection.** `knowledge/retrieval.py` does bounded (small-k, truncated,
    capped) BM25 OR-match retrieval, wired into `enforce.evaluate_userpromptsubmit` (injects
    additionalContext on the non-blocking path) and extended into the SessionStart hook
    (query = last user turn). Local only — vault content never leaves the machine.
  - **Daily integrity audit.** `knowledge/ops.py` + `precept audit`: re-runs the auditor and
    an unfiled-knowledge scan, surfacing rename / placement / missing-frontmatter /
    missing-sources / unfiled findings as PENDING proposals (never auto-applied; renamer stays
    dry-run). A once-per-day THROTTLE (stamp in state_dir) lets it ride SessionStart without
    nagging. Guarded ANN-WATCH seam: emits an HNSW suggestion when a future `vectors` table
    exceeds ~1M rows; a clean no-op today (vectors not built).
  - 20 new tests (154 total green); ruff clean on `precept/`.
- **Backlog items 1, 2, 3, 6 — 2026-06-30.** Built by a background pipeline.
  - **#1 Incremental detection.** Per-session CURSOR (`paths.detect_cursor`) records the
    transcript offset already classified; each Stop classifies only the new tail and
    advances it (resets if the transcript shrinks). A recall-biased regex PRE-FILTER
    (`detect.looks_like_correction`) is a pure COST GATE — it only decides whether to spend
    the LLM call; the correction classification stays the LLM. A per-session LOCK
    (`detect._DetectLock`, an atomic `os.mkdir`, stale-reclaimed) makes detection idempotent
    under near-simultaneous Stops. `hooks._spawn_detect` threads `session_id` + `cwd` through.
  - **#2 Robust hook paths + doctor.** `install.resolve_command` writes the ABSOLUTE path to
    each console script into settings.json (venv-not-on-PATH safe); entry detection is now
    basename-keyed so the strip stays an exact inverse. New `precept/doctor.py` verifies each
    hook is registered AND reachable AND wired to the right script; surfaced by `precept doctor`
    (with `--strict` for CI).
  - **#3 Proactive review.** Detected lessons carry `needs_review`; `precept/review.py` builds
    an additionalContext prompt ("I drafted a rule … keep it?") injected on the Stop allow-path
    and by a new SessionStart hook (`precept-hook-sessionstart`, with pyproject + install entry).
    The PENDING gate is untouched — this changes HOW the user is asked, not WHETHER they approve;
    `keep`/`delete` clear the flag.
  - **#6 Governance.** `precept/governance.py`: decay (active rule, fire_count 0 past a
    threshold -> propose archive), supersede (old -> ARCHIVED with `superseded_by`, new gets
    `supersedes`), conflict-detection via the SAME injectable judge seam (`judge.conflict_verdict`,
    fail-open). Surfaced by `precept govern`; archived rules are excluded from the compile cache
    (already gated on status=ACTIVE), so they stop enforcing on recompile. Nothing auto-applied.
  - 26 new tests (125 total green); evals 100%/0%; ruff clean on all new code.
- **Stop-verdict layer (#4 + #5 core), 2026-06-29.** AI-based claim detection (regex
  retired), judgment relevance-gate plumbing, and ONE consolidated verdict call per turn
  at Stop, with the `verdict_fn` injection seam keeping the Tier-1 eval deterministic.
  Fail-open intact; hot path stays stdlib. 56 tests, evals green. (Built by a background
  plan->implement->test->review pipeline; reviewer verdict: ship.)
