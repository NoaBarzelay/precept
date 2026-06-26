# Decision log

The full design + research arc lives in the private project brief. This is the
in-repo summary of the load-bearing engineering decisions, with the *why*.

## Language & shape
- **Python**, local-first CLI + hooks (not a web app). Deliberately the inverse of
  the author's TypeScript project: runtime chosen by product center-of-gravity. The
  product is a local enforcement daemon + catalog + eval harness, where Python is
  the lingua franca (Anthropic SDK, Claude Code hook examples, eval tooling).

## Enforcement (the wedge)
- Only **hooks + permission-deny + subagent tool-scoping** are HARD; everything else
  is labeled SOFT. Verified against the live hook contract:
  - PreToolUse → exit 0 + `{"hookSpecificOutput":{"permissionDecision":"deny"|...}}`
    (richer than exit-2; supports `updatedInput` for rewrites).
  - Stop → `{"decision":"block","reason":...}` to refuse finishing. The old
    `stop_hook_active` field / 8-block cap are **gone** from the current docs — do not
    assume them; re-verify at codegen (the contract already moved once).
- **Rules are data, never code.** `enforce.py` is a fixed interpreter over compiled
  JSON; it never `eval`s a rule. Regex inputs are length-capped (re2 is the upgrade).
- Decision precedence (Cedar/OPA): **deny > ask > rewrite > allow**; no match → allow.

## Storage (local-first)
- **Markdown cards = source of truth** (safe in the synced vault; git = audit log).
- **Derived SQLite/policy cache = local disk only** (`~/.local/state/precept`), never
  a cloud-synced folder — SQLite corrupts under iCloud/Dropbox/NFS sync (SQLite's own
  `howtocorrupt`). It's disposable; `precept compile`/`reindex` rebuilds it.
- All writes to real targets are **atomic** (temp-in-same-dir → fsync → `os.replace`).
- SQLite preamble everywhere: WAL + `busy_timeout` + `synchronous=NORMAL`.

## Pipeline
- One shared **DETECT → COMPILE → REVIEW → COMMIT → ENFORCE** spine.
- DETECT: Haiku structured extraction, leading `chain_of_thought`, **abstain-aware**
  (`MaybeLesson`), provenance gate (user-typed turns only), **fail-closed**.
- The human **keep/veto** gate is the credibility core — nothing enforces until kept.
- Confidence is **grounded** (quote present? imperative? deterministic? kept? fires?),
  not an LLM self-report (verbalized confidence is miscalibrated).

## Evals (the #1 signal)
- Two-tier: deterministic confusion matrix (the trustworthy headline) + a paired,
  multi-trial, error-barred live before/after. Metric = corrected-behavior rate.

## Knowledge recall
- **Keyword-first** (SQLite FTS5 + metadata filter). Add sqlite-vec embeddings only
  if a Recall@k eval proves keyword search misses (measured decision > "semantic from
  day one"; single-vector embeddings underperform on terse, jargon-dense cards).

## Host-drift
- All Claude Code integration behind `adapters/claude_code.py` with CI JSONL fixtures;
  hooks **fail open** on an unrecognized input shape.
