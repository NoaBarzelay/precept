# Decision log

This is the in-repo summary of the load-bearing engineering decisions, with the *why*.

## Language & shape
- Local-first CLI + hooks (not a web app): a local enforcement daemon + catalog + eval harness.
- **Decided target: TypeScript on Bun.** Best-in-class for a Claude Code extension as one language: host-native (Claude Code is itself Node/TS), the fastest startup of the interpreted runtimes (Bun 8 to 15 ms), single-binary distribution (kills the venv/pipx drift), built-in SQLite for the catalog, and a first-class AI SDK (Anthropic TS SDK + Vercel AI SDK, with Zod for model-output validation). The one real risk is Bun's youth; Node is the drop-in fallback. Full analysis, the July 2026 best-in-class scan, the first-principles characteristic breakdown, the scorecard, and the honest dissent are in [docs/LANGUAGE.md](docs/LANGUAGE.md).
- **Current implementation: Python**, and this repo is Python until a migration lands (not started). Python is the close second, strongest on the eval and statistics tooling (the number-one signal), which is the heaviest thing a migration has to port. Honest status: Python now, TypeScript on Bun next.

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

Governing rule: the **least-power principle** (W3C TAG): enforce a correction with the least powerful mechanism that can express it, because a predicate or AST match is analyzable, auditable, and deterministic where a model verdict is none of those. Climb a tier only when the cheaper one cannot express the rule. The LLM-cascade work (FrugalGPT, RouteLLM) is the same ordering for cost: a predicate or AST check is sub-millisecond, an LLM judge at the gate is 300 to 2000 ms per call. Production guardrail stacks already run deterministic-first with a model fallback (Arthur.ai: "keep pre-LLM guardrails fast and deterministic, avoid LLM checks unless necessary"; Braintrust: deterministic checks for anything measurable, an LLM judge only for the subjective-but-describable). Emerging consensus, not a novel bet.

Decision: a **checker cascade**; the router picks the cheapest sufficient tier; keep/veto still gates all of it.
1. **Structured predicate** (lead, exists). `field op value` on the tool input, e.g. Bash `command` starts_with `pip install`. Deterministic, exact, auditable (the OPA/Cedar shape).
2. **re2 for the `regex` op** (`re` → re2). Linear-time NFA simulation, immune to catastrophic backtracking, built for untrusted patterns. This **deletes `safe_regex.py`**: no compile-reject heuristic, no wall-clock thread. Cost: re2 has no backreferences or look-around, which model-authored matchers do not need. Already this log's stated direction.
3. **STRUCTURAL (AST) check kind** (new), for rules about code content. Match the parse tree, not the text: stdlib **`ast`** for Python (zero dependency, the common case; needs a name-binding pass to follow aliases), **tree-sitter** for other languages (one embeddable C library, error-recovering concrete syntax tree, 35+ grammars, used by GitHub and Neovim). Deterministic and model-free, so it stays on the hot path. "no bare `except`", "`subprocess.run` must set `shell=False`" become AST queries: formatting- and alias-robust, none of regex's comment/string false positives.
4. **JUDGMENT verdict** (keep). For intent nothing deterministic expresses; the model verdict at the gate. Off the deterministic path (it carries the token cost and the eval noise, which is why it is reported with a CI, not a point estimate). The fallback, not the default, and never the sole gate on a must-hold rule: even a fine-tuned safety classifier (Llama Guard) misses roughly 20% of adversarial cases on average and is miscalibrated under attack.

The **router is the real work.** The synthesizer drafts a `check_kind` but has no STRUCTURAL option today, so a code-structure rule is forced onto regex-content or punted to JUDGMENT. STRUCTURAL means classifying a correction as lexical (predicate/re2), structural (AST), or intent (verdict); a misroute silently under-enforces, so it rides the keep/veto gate and the coverage audit.

Rejected alternatives:
- **LLM judge for everything** → forfeits the model-free hot path (N2), a token cost per guarded call, and inherits agentic-eval noise (identical runs swing several points). The verdict tier earns its place only where nothing deterministic can express the rule.
- **re2 alone** → fixes efficiency and the ReDoS smell, not comprehensiveness on code. Necessary, not sufficient.
- **Semgrep as the engine** → the reference structural matcher, but its cross-file analysis is a proprietary Pro engine (the OSS engine is single-function), and it is a heavy binary plus per-language YAML rules. Borrow its ideas (metavariables, ellipsis, alias resolution), not its dependency; `ast` + tree-sitter give the structural win locally and model-free.
- **tree-sitter for Python too** → no; stdlib `ast` is zero-dependency for the common case. tree-sitter is the multi-language upgrade and it does add a compiled dependency to the hot path, which relaxes N2 from "stdlib-only" to "no model, no network" for non-Python rules. Taken only when a non-Python structural rule actually appears.

Honest dissent (the genuine tension, unsettled):
- **Camp A, lean on the model.** The *Bitter Lesson* (Sutton): general methods that scale with compute beat hand-engineered knowledge, and a rule DSL is exactly that knowledge. Stronger and empirical, **criteria drift** (Shankar et al., UIST 2024): you cannot fully pre-specify a rule set, because defining criteria and applying them are entangled, so a rigid predicate/AST layer is always incomplete where an LLM judge adapts without a rewrite.
- **Camp B, keep the hot path deterministic.** A probabilistic guard is not a control (Civic): a model cannot reliably tell benign from malicious under prompt injection, so a must-fire boundary has to be deterministic and outside language manipulation. A model verdict is not repeatable even at temperature 0 (non-deterministic by construction from batch-invariance and server load, Thinking Machines Lab; agentic pass rates swing 2 to 6 points run to run, Bjarnason et al. on SWE-bench), so a rule that must fire every time cannot ride it. Authorization should be declarative and analyzable (OPA/Cedar).
- **Resolution:** the disagreement is about *which* rule goes in *which* tier, not whether to tier. Camp B owns must-fire safety and permission gates; Camp A's criteria-drift point owns fuzzy, evolving intent, which is exactly where the cascade already routes to the verdict tier. The contested case is a boundary rule like "do not call the client directly": a clean AST match, or does it need semantic understanding of an indirection? Mis-tiering it either overspends on a model or ships a brittle rule. That boundary call is the router's job, and it is open, not solved.

Failure modes (project-specific):
- **Unparseable input** (a half-written Edit body): the AST check cannot run → fall back to predicate/re2 or JUDGMENT, never block on a parse error (fail-open, N1).
- **`ast` and aliases:** plain `ast` does not follow `import x as y` → resolve binding, or route alias-sensitive rules to tree-sitter.
- **Misroute** (a structural rule left on the regex tier): looks enforced, silently misses variants → caught by the sampled coverage audit, not by the matcher.

Migration: (1) `re` → re2, delete `safe_regex.py`, keep the `regex` op contract; (2) add STRUCTURAL on stdlib `ast` plus the synthesizer route, for Python code rules; (3) tree-sitter only when a non-Python structural rule appears.

Sources: [RE2](https://github.com/google/re2); [Cloudflare 2019 ReDoS outage](https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/); [OWASP ReDoS](https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS); [Semgrep](https://github.com/semgrep/semgrep); [tree-sitter](https://tree-sitter.github.io/tree-sitter/); [Python `ast`](https://docs.python.org/3/library/ast.html); [W3C Rule of Least Power](https://www.w3.org/2001/tag/doc/leastPower.html); [FrugalGPT](https://arxiv.org/abs/2305.05176); [non-determinism of temp-0 LLMs (Atil et al.)](https://arxiv.org/abs/2408.04667); [criteria drift (Shankar et al.)](https://arxiv.org/abs/2404.12272); [temp-0 nondeterminism (Thinking Machines Lab)](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/); [randomness in agentic evals (Bjarnason et al.)](https://arxiv.org/abs/2602.07150); [guardrail latency figures (QASkills)](https://qaskills.sh/blog/llm-guardrails-testing-guide-2026); [jailbreak-guardrail evaluation (SoK)](https://arxiv.org/abs/2506.10597); OPA and Cedar (openpolicyagent.org, cedarpolicy.com).

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

## Check-language validation: evidence, not proof (2026-07-19)
Refines the Matchers section above. The runtime **cascade** (predicate, regex, structural,
verdict) is unchanged; this is about **authoring-time** validation: how the system decides a
check is honest before it lets it block.
- **Decision: validate a check against recorded tool-call history, not by symbolic proof.**
  Reachability = does it match a concrete call (from history or a reviewed example);
  contradiction = did two checks disagree on a recorded call; subsumption = did one check's
  matches cover another's; breadth = how many recorded calls it would have fired on.
- **Why not proof.** Reachability/contradiction/subsumption over strings, globs, and integer
  constraints is an automata/SMT problem. In the TypeScript target that is a multi-megabyte
  solver (too heavy for any hook budget) or a hand-rolled automata engine (a multi-week
  subproject). It also answers only three of the four questions; **breadth has no symbolic
  form**, and breadth is what the review gate needs.
- **Cost (stated honestly).** Evidence validation is unsound: a contradiction or redundancy
  between two checks that never co-occurred in history is missed. Reachability is NOT in this
  gap (a check with no historical match is validated by a reviewed example instead).
- **Why it is safe anyway.** The runtime rules absorb the miss: a false or conflicting check
  fails toward not enforcing; a colliding rewrite applies nothing; the sampled hindsight audit
  is the backstop. Authoring-time validation is an advisory pass over the past, not a guarantee
  about the future.
- **Second-order win (the real reason).** The review gate shows a rule's recorded firing
  history instead of a rationale ("would have fired on 14 calls, here are three, should it have
  blocked these?"). That is cognitive forcing on real cases, and it lets a probationary rule
  graduate retroactively from history without ever interrupting a live session.
- **Rewrite/`updatedInput` kept**, order independence preserved at RUNTIME: a field targeted by
  two rewrites applies none and records. Authoring-time field-collision flagging over history is
  advisory on top. (Supersedes the earlier "drop rewrite to keep order independence" direction.)

## Delivery: TypeScript rebuild as a strangler, knowledge-first (2026-07-19)
- **Decision: replace one seam at a time behind the shared markdown catalog; never a flag day.**
  The cards are the language-agnostic source of truth, so the Python build and the TypeScript
  build operate on the same catalog and a working system exists at every step.
- **Coordination between the two runtimes** is by per-card version compare-and-swap (the same
  path Storage uses for any second writer), NOT a cross-runtime lock. **Operational state**
  (queue, counters, ledgers) is single-owner per seam, handed over when that seam migrates, so
  the newer-major refusal rule cannot strand the trailing runtime.
- **Order by value per session, not the dependency graph:** (1) knowledge (O2) first, since a
  saved fact pays off in the very next session and needs no enforcement machinery; (2) the hot
  path, the smallest self-contained piece and where Bun startup earns the move; (3) preference
  enforcement authoring (O1) last, since it depends on accumulated corrections and on the hot
  path to run against.
- This **inverts the ROADMAP's enforcement-first framing** on purpose: enforcement leads there
  because it already exists in Python; from a cold start it is the last half to deliver value.

## Hook distribution: bundle, do not compile (2026-07-19)
- **Decision: bundle the hot hook entrypoints to one dependency-free script; compile only the
  CLI.** Measured on the target machine: a `bun build --compile` binary cold-starts ~1.7x
  SLOWER than running the script (42 ms vs 26 ms), so compiling costs the exact budget it was
  meant to protect. Bundling keeps the 26 ms startup and erases the `node_modules` tree, which
  is the drift class this project has already hit; hooks run with the session cwd, so relative
  resolution is hostile.
- Pin the hooks to an absolute interpreter path (fixes PATH variance) and have the startup
  diagnostic verify it still exists (an in-place runtime upgrade or a machine move can break it).
- **No schema library on the hot path**: importing one costs more than the whole runtime
  startup; the hook hand-narrows the host's own JSON. Model output still gets full validation in
  the inference module, where a network call dominates.
- **Spawn per call**, with a warm loopback daemon (a hook fronting it) as a costed escape hatch
  if the D1 latency budget fails a test. Not adopted preemptively: spawn has no lifecycle,
  staleness, or version-skew problem.
- **Retrieval stays full-text (FTS), no embeddings today.** Measured 0.8 ms over 500 docs, and
  `loadExtension` throws under Bun's SQLite on macOS, so a vector extension would need a custom
  SQLite build shipped alongside. A dense arm, if ever earned by a Recall@k eval, can be
  brute-force cosine over a few hundred vectors in plain TypeScript, no extension.

## Source of truth: markdown cards, scrutinized (2026-07-19)
The Storage section above asserts "markdown cards = source of truth." That was inherited, not
scrutinized. Running the protocol now, because it is load-bearing.

**The decision is not cards-vs-database. It is four orthogonal axes:** record format
(markdown+frontmatter / structured file / DB row), storage engine (git-tracked files / embedded
DB / git-for-data / sync engine), temporal model (mutable + external history / bi-temporal
columns / append-only event log), and human-edit surface (edit truth / edit a render and
round-trip / gate-only).

**What the leading systems choose (as reference, not authority).** Anthropic Agent Skills and
Claude Code memory: markdown files on the filesystem, for transparency, audit, and
self-authoring. Zep/Graphiti: bi-temporal knowledge graph, invalidate-never-delete. ACE:
structured itemized deltas with deterministic merge. Mem0/Letta: DB-backed vector or block
stores. No consensus; each optimizes a different thing. The one convergence is that all separate
a legible surface from a temporal/retrieval engine (source-of-truth vs derived projection). The
memory benchmarks are vendor-published and contested (a filesystem+grep baseline beat the
branded systems on LOCOMO), so this input is a tiebreaker, not a decider.

**The deciding factor is project-specific: the corpus is a few hundred entries.** At that scale
the whole catalog folds in memory, so contradiction, subsumption, and retrieval need no database
engine, only a disposable local index. The requirements that looked like they demanded a DB
(bi-temporal validity, contradiction, retrieval) demand *structured, loadable* data, which
frontmatter is, not a query engine. Two further specifics settle it: the host commit targets are
markdown regardless (Convention -> rules file, Skill -> SKILL.md), so cards-as-truth removes a
translation layer; and git already is an append-and-invalidate log over the cards, supplying
transaction-time history for free.

**Decision: markdown cards remain the source of truth, for THIS use case.** Real risks here are
audit-legibility and never-stranding-data (portfolio + longevity), not query throughput or
concurrent merge. Cards + git + a typed frontmatter schema hit exactly those.

**Options considered and rejected for this use case:**
- **DB of record (SQLite/graph):** not sync-safe in the vault, not hand-editable in Obsidian, no
  free line-diff history, and it still needs a markdown render for the host targets. Solves a
  scale/query problem this corpus does not have.
- **Event-sourcing engine:** the elegant fit for provenance + bi-temporal + reversibility, and
  the design already keeps evidence and decisions as immutable append-only records. But at a few
  hundred entries the replay/projection/event-schema-migration machinery is cost with no return;
  git already logs, and provenance is already carried by the four separate record layers.
- **CRDT / local-first sync engine (Automerge, Electric, libSQL replicas):** solves automatic
  merge of concurrent multi-device edits. The only concurrency here is parallel Claude Code
  sessions on one machine, handled by per-card version compare-and-swap plus git. A CRDT is a
  dependency and a failure surface for a problem not present.

**Three fixes this scrutiny surfaced (now in ARCHITECTURE.md storage):**
1. Frontmatter is a validated, versioned typed contract, checked on every read and write, not
   freeform YAML.
2. Valid-time is explicit frontmatter (`valid_from`, `valid_until` or the condition);
   transaction-time comes from git. Bi-temporal without an event engine.
3. Currency is invalidate-not-delete (retire/supersede set a status, keep the card, recover from
   git); only a removal on request hard-deletes. Zep's one portable rule, without Zep's graph.

**Revisit if:** the corpus outgrows in-memory folding (low tens of thousands), or multi-device
concurrent hand-editing becomes real. Either would reopen the sync-engine option.

## Build decisions from the TypeScript rebuild (2026-07-20)
Recorded so the log matches the code, not just the intent above.

- **Lexical regex is a hand-rolled Thompson NFA, not re2.** The Matchers section above names re2
  for the `regex` op. re2 has no first-party Bun binding and would add a native dependency to the
  hot path, which the distribution decision works to avoid. A small linear-time NFA (single-pass
  simulation, no backtracking) delivers the same guarantee (a model-authored pattern cannot cause
  a ReDoS) with zero dependencies. The structural/AST tier (tree-sitter) is still deferred to the
  turn-end path and unbuilt. Cost: a hand-rolled engine is more code to be wrong; it carries a
  scaling test that asserts linear time, and it is the one place the build reverses a logged
  direction, recorded here rather than left silent.
- **Scope is compiled into the check, not enforced separately.** A rule's scope (repository or
  path) becomes an implicit conjunct on its compiled check, so the enforcement engine stays a
  single evaluator over one boolean and a repo-scoped rule simply does not match outside its repo.
  Language and situation scopes have no fact to check against, so they enforce as authored.
- **Enforcement faults are returned, not logged in place.** `enforce` is pure (no IO); it returns
  the rules whose check threw, and the interception entrypoint records them, so fail-open stays
  recorded (N1) without giving the pure evaluator a dependency on the fault log.
- **Transcript reading lives in `host`, and the evidence contract moved to `domain`.** The session
  transcript is the host's own JSONL wire format, so parsing it belongs beside the hook-event parser
  (`host/transcript.ts`), and a second host is a second adapter. `host` may not import `record`
  (dependency rule), so the `EvidenceRecord` interface moved to `domain/evidence.ts` (the log
  functions stay in `record/evidence.ts`, which re-exports the type); now `host` drafts evidence and
  `record` persists it without either crossing the boundary. The provenance gate is the transcript's
  own shape: a human-typed turn has string (or text-block) content and is neither a tool-result turn
  nor a subagent (sidechain) turn, so only genuine user input can ever source a blocking entry.
- **Silent edits are the agent's last write to a path versus its disk state, compared by kind.** The
  reader diffs the final authoring op per file against the file's current content (R1.1). A full write
  (`Write`, whole-file `content`) diverges by inequality; a fragment write (`Edit`/`MultiEdit`/
  `NotebookEdit`, replacement snippets) diverges only when a snippet the agent authored is no longer
  present, meaning the user removed or rewrote it. Comparing a fragment to the whole file by equality
  (the first cut) fired on every edited file; the kind-aware check is the fix. A matching or unreadable
  file yields no signal, and the injected final-state read keeps assembly offline-testable. Signal kind
  is a cheap cue only (a correction-word regex tags correction vs instruction); the detector still
  judges intent from the raw turns, and evidence is recorded broadly so the R1.14 hindsight pass has
  the raw signal. Stored turns and payloads are capped (20k chars, truncation marked) so one generated
  file cannot bloat the append-only log.
- **Install self-marks its hook commands rather than tracking them in a sidecar.** Each command
  `install` writes into `~/.claude/settings.json` is prefixed with a `PRECEPT_MANAGED=1` shell
  assignment, and the hook runs the entrypoint as `bun <absolute entrypoint path>` (the runtime is
  `process.execPath`, absolute so Claude Code's own PATH need not include bun). Precept entries are then
  identifiable in place, so install strips its own and re-adds (idempotent) and uninstall removes exactly
  its own, leaving the user's hooks and every other setting untouched (N8, exact inverse). The marker is
  a harmless env assignment nothing reads; it avoids adding a custom JSON key the host might reject, which
  is why the Python reference keyed on a command-name prefix and this keys on the env marker (bun files
  have no distinctive script name to key on). Writes go temp then atomic rename with a `.bak`. The
  settings path is env-overridable (`PRECEPT_CLAUDE_HOME`) so tests never touch the real file. The
  recursion guard is not install's concern: `CliClient` sets the `PRECEPT_INFERENCE_SUBPROCESS` sentinel
  and `--setting-sources project` when it spawns `claude -p`, so a nested run no-ops Precept's user-source
  hooks. PreToolUse registers the `*` matcher (guard every tool); per-tool narrowing for felt latency is a
  later optimization regenerated on `compile`, not a correctness gap.
- **Idempotency is content-derived ids plus dedup, not a cursor.** Each evidence id is an FNV-1a hash
  of its content (the turn window, or the path + agent output + final state), so re-processing the
  whole transcript re-yields the same id for an unchanged observation (the caller drops it) and a fresh
  id for a genuinely new one (recorded). A first cut used a per-session cursor of consumed entries;
  removed, because positional ids collided with the dedup on the rotation/compaction reset path it
  existed to handle, and index shifts could skip a new-but-early turn. Content ids are position-
  independent, which is strictly more correct under a compacted or rotated transcript and also lets a
  divergence that appears after a SessionEnd be caught on the next one. The reader keys the human-typed
  provenance gate on the transcript's own shape (string/text content, not a tool-result, not a
  sidechain subagent) rather than on the entry `type`, so an unversioned host-format change degrades
  toward capture, not toward dropping a turn. An explicit provenance field on the evidence record
  (ARCHITECTURE 6.2 names one) is deferred: nothing reads it yet (the gate keys on the candidate's
  signal kind), and the two produced classes map cleanly from signal kind for now.
- **Not yet built, so not yet claimed as in-place** despite the intent above: the per-card version
  CAS and the lock around the primary commit path (only the lifecycle read-modify-write is locked
  today), `rewrite`/`updatedInput` as an outcome (the engine is deny/ask/allow), git as the
  transaction-time store (asserted, not read by code), and the whole currency/governance surface.
