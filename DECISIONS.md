# Decision log

This is the in-repo summary of the load-bearing engineering decisions, with the *why*.

## Language & shape
- **Python**, local-first CLI + hooks (not a web app). Runtime chosen by product center-of-gravity. The
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

## Matchers (predicate → re2 → AST → verdict)
The critique was "regex is inefficient and incomprehensive, matchers are outdated." Grounded against the code first: the backbone is already **structured predicates**, not regex. A `Condition` is `field op value` over a tool input (Cedar PARC shape); regex is one `op` beside `contains/equals/starts_with/glob`, already ReDoS-guarded (`safe_regex.py`) and length-capped. A **JUDGMENT** verdict tier (an AI decision at the Stop gate) already handles rules with no mechanical check. So the change is surgical, two real gaps:
- **Efficiency.** The `regex` op runs on Python `re` (backtracking, no timeout), so it needs a compile-time nested-quantifier reject plus a runtime wall-clock thread. That guard is the smell: the engine, not the pattern, is the hazard. Cloudflare's 27-minute global outage in 2019 was one PCRE sub-pattern (`.*.*=.*`); the fix was re2 / Rust regex, both linear-time.
- **Comprehensiveness on code.** Regex matches regular languages; code structure is not regular. On an Edit/Write body a lexical pattern breaks on aliasing (`import subprocess as sp; sp.run(...)`), whitespace/multiline, and lookalikes in comments and string literals. This is why SAST left grep for AST (Semgrep = "semantic grep," matches the parse tree and resolves import aliases).

Governing rule: the **least-power principle** (W3C TAG): enforce a correction with the least powerful mechanism that can express it, because a predicate or AST match is analyzable, auditable, and deterministic where a model verdict is none of those. Climb a tier only when the cheaper one cannot express the rule. The LLM-cascade work (FrugalGPT, RouteLLM) is the same ordering for cost, and production guardrail stacks already run deterministic-first with a model fallback (Arthur.ai: "keep pre-LLM guardrails fast and deterministic, avoid LLM checks unless necessary"; Braintrust: deterministic checks for anything measurable, an LLM judge only for the subjective-but-describable). Emerging consensus, not a novel bet.

Decision: a **checker cascade**; the router picks the cheapest sufficient tier; keep/veto still gates all of it.
1. **Structured predicate** (lead, exists). `field op value` on the tool input, e.g. Bash `command` starts_with `pip install`. Deterministic, exact, auditable (the OPA/Cedar shape).
2. **re2 for the `regex` op** (`re` → re2). Linear-time NFA simulation, immune to catastrophic backtracking, built for untrusted patterns. This **deletes `safe_regex.py`**: no compile-reject heuristic, no wall-clock thread. Cost: re2 has no backreferences or look-around, which model-authored matchers do not need. Already this log's stated direction.
3. **STRUCTURAL (AST) check kind** (new), for rules about code content. Match the parse tree, not the text: stdlib **`ast`** for Python (zero dependency, the common case; needs a name-binding pass to follow aliases), **tree-sitter** for other languages (one embeddable C library, error-recovering concrete syntax tree, 35+ grammars, used by GitHub and Neovim). Deterministic and model-free, so it stays on the hot path. "no bare `except`", "`subprocess.run` must set `shell=False`" become AST queries: formatting- and alias-robust, none of regex's comment/string false positives.
4. **JUDGMENT verdict** (keep). For intent nothing deterministic expresses; the model verdict at the gate. Off the deterministic path (it carries the token cost and the eval noise, which is why it is reported with a CI, not a point estimate). The fallback, not the default.

The **router is the real work.** The synthesizer drafts a `check_kind` but has no STRUCTURAL option today, so a code-structure rule is forced onto regex-content or punted to JUDGMENT. STRUCTURAL means classifying a correction as lexical (predicate/re2), structural (AST), or intent (verdict); a misroute silently under-enforces, so it rides the keep/veto gate and the coverage audit (README Open questions #4).

Rejected alternatives:
- **LLM judge for everything** → forfeits the model-free hot path (N2), a token cost per guarded call, and inherits agentic-eval noise (identical runs swing several points). The verdict tier earns its place only where nothing deterministic can express the rule.
- **re2 alone** → fixes efficiency and the ReDoS smell, not comprehensiveness on code. Necessary, not sufficient.
- **Semgrep as the engine** → the reference structural matcher, but its cross-file analysis is a proprietary Pro engine (the OSS engine is single-function), and it is a heavy binary plus per-language YAML rules. Borrow its ideas (metavariables, ellipsis, alias resolution), not its dependency; `ast` + tree-sitter give the structural win locally and model-free.
- **tree-sitter for Python too** → no; stdlib `ast` is zero-dependency for the common case. tree-sitter is the multi-language upgrade and it does add a compiled dependency to the hot path, which relaxes N2 from "stdlib-only" to "no model, no network" for non-Python rules. Taken only when a non-Python structural rule actually appears.

Honest dissent (the genuine tension, unsettled):
- **Camp A, lean on the model.** The *Bitter Lesson* (Sutton): general methods that scale with compute beat hand-engineered knowledge, and a rule DSL is exactly that knowledge. Stronger and empirical, **criteria drift** (Shankar et al., UIST 2024): you cannot fully pre-specify a rule set, because defining criteria and applying them are entangled, so a rigid predicate/AST layer is always incomplete where an LLM judge adapts without a rewrite.
- **Camp B, keep the hot path deterministic.** A probabilistic guard is not a control (Civic): a model cannot reliably tell benign from malicious under prompt injection, so a must-fire boundary has to be deterministic and outside language manipulation (even temp-0 LLMs vary up to 15% across identical runs, Atil et al.); authorization should be declarative and analyzable (OPA/Cedar).
- **Resolution:** the disagreement is about *which* rule goes in *which* tier, not whether to tier. Camp B owns must-fire safety and permission gates; Camp A's criteria-drift point owns fuzzy, evolving intent, which is exactly where the cascade already routes to the verdict tier. The contested case is a boundary rule like "do not call the client directly": a clean AST match, or does it need semantic understanding of an indirection? Mis-tiering it either overspends on a model or ships a brittle rule. That boundary call is the router's job, and it is open, not solved.

Failure modes (project-specific):
- **Unparseable input** (a half-written Edit body): the AST check cannot run → fall back to predicate/re2 or JUDGMENT, never block on a parse error (fail-open, N1).
- **`ast` and aliases:** plain `ast` does not follow `import x as y` → resolve binding, or route alias-sensitive rules to tree-sitter.
- **Misroute** (a structural rule left on the regex tier): looks enforced, silently misses variants → caught by the sampled coverage audit, not by the matcher.

Migration: (1) `re` → re2, delete `safe_regex.py`, keep the `regex` op contract; (2) add STRUCTURAL on stdlib `ast` plus the synthesizer route, for Python code rules; (3) tree-sitter only when a non-Python structural rule appears.

Sources: [RE2](https://github.com/google/re2); [Cloudflare 2019 ReDoS outage](https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/); [OWASP ReDoS](https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS); [Semgrep](https://github.com/semgrep/semgrep); [tree-sitter](https://tree-sitter.github.io/tree-sitter/); [Python `ast`](https://docs.python.org/3/library/ast.html); [W3C Rule of Least Power](https://www.w3.org/2001/tag/doc/leastPower.html); [FrugalGPT](https://arxiv.org/abs/2305.05176); [non-determinism of temp-0 LLMs (Atil et al.)](https://arxiv.org/abs/2408.04667); [criteria drift (Shankar et al.)](https://arxiv.org/abs/2404.12272); OPA and Cedar (openpolicyagent.org, cedarpolicy.com).

## Storage (local-first)
- **Markdown cards = source of truth** (safe in the synced vault; plain-text and diffable, so the catalog can be kept under version control for a full lifecycle history).
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
