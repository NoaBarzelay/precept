# Precept

Some agent behaviors should be left to the model's judgment. Others should never be a matter of judgment at all. Precept is the machinery for drawing that line: it compiles the corrections you make inside Claude Code into typed artifacts, and the mechanically-checkable subset compiles into Claude Code hooks that *block* (deny a tool call, block a Stop), not notes that nudge. Nothing enforces until you approve it.

*The strongest thing here is not the enforcement, it is how it is measured: a deterministic confusion matrix over a committed golden set, plus a live before/after reported as a paired delta with a 95% CI, because agentic-eval infra noise alone swings scores by several points. Both are below.*

Built with Claude Code, on itself. The architecture, the HARD/SOFT tier split, the fail-open judgment gate, and the eval methodology are the design, and the design is mine; the model was a fast implementer. That the author can say precisely which parts were the model's and which were the design is itself the signal.

**Reading this repo:** engineering decisions and their reasons are in [`DECISIONS.md`](DECISIONS.md); the planned direction is in [`ROADMAP.md`](ROADMAP.md); the proof is the deterministic scorecard below plus `pytest` (250 hermetic, fully offline tests); the enforcement core is [`precept/enforce.py`](precept/enforce.py).

<!-- demo.gif to be recorded: correct the agent once, next session is blocked -->

Correct the agent once ("run the tests before you say it works"). A later session is blocked from claiming success until the tests actually ran.

## The problem

Agent "memory" captures what you tell it and then obeys it around 70% of the time. That is fine for preferences and wrong for invariants. The reason is architectural, not a tuning gap: `CLAUDE.md`, skills, and rules files are delivered to the model as *context*. Claude Code's own docs describe them as context, not enforced configuration, with no guarantee of strict compliance. The only layer Claude Code runs deterministically, outside the model's discretion, is hooks.

So the interesting question is not how to remind the model harder. It is: of the things you correct, which are mechanically checkable, and can we compile exactly those into a blocking guardrail while being honest that the rest only steer. That split, checkable-so-enforce versus fuzzy-so-steer, is what Precept is built around.

## How it works

One correction becomes a `Lesson` (auditable data). A `Lesson` compiles to zero or more typed `Policy` objects. Determinism is not self-declared by the model at extraction time; it is *earned* at COMPILE, when a stronger model is asked to produce an exact, structured matcher and the result must pass a typed validator gate. If it cannot produce one, the lesson stays soft. Nothing is enforced until a human keeps it.

```
session transcript
      |  Stop / SessionEnd hook (fire-and-forget, fail-CLOSED)
      v
   DETECT   Haiku structured extraction -> MaybeLesson.
            Abstain-aware, reads only genuine user-typed turns (provenance gate).
            A false lesson is worse than a missed one, so it abstains by default.
      v
   COMPILE  Lesson -> 1..N typed Policy (Cedar-style precedence).
            Determinism is EARNED here: a structured matcher that passes a typed
            validator, or the lesson stays soft. The model does not get to assert
            "this is enforceable."
      v
   REVIEW   `precept keep` / `precept delete`. The human gate, and the credibility
            core: nothing enforces until a person keeps it. PENDING -> ACTIVE.
      v
   COMMIT   markdown card is the source of truth (plain text, diffable, safe in a
            synced vault); compiled policies.json is the disposable hot path,
            rebuildable from the cards.
      v
   ENFORCE  PreToolUse / Stop / UserPromptSubmit hooks read the JSON cache.
            Stdlib only, no LLM, fast.
```

DETECT fails *closed* (abstains rather than guess). ENFORCE fails *open* (a missing key, an unreadable cache, or an unrecognized transcript shape never wedges a session). Detection is conservative about what it learns; enforcement is conservative about what it breaks.

## Enforcement is validator-enforced, not asserted

Precept labels every artifact HARD or SOFT and only claims enforcement for the HARD tier.

- **HARD** is exactly three mechanisms Claude Code runs without the model's cooperation: hooks (PreToolUse deny, Stop block, UserPromptSubmit block), the `permissions` `deny` array in `settings.json`, and subagent tool-scoping. These are real capability boundaries.
- **SOFT** is everything delivered as context: knowledge notes, conventions, skills, output styles. Precept guarantees the artifact is written correctly and atomically; it does not claim the model will obey it, because it can't.

That boundary is encoded in the type system, so overclaiming is a `ValueError`, not a judgment call. In `models.py`, `Policy._shape_matches_kind` rejects a HARD tier attached to an event that cannot block:

```python
if self.enforcement_tier is Tier.HARD and self.hook_event not in BLOCKABLE_EVENTS:
    raise ValueError(
        f"HARD tier requires a blockable event; {self.hook_event} cannot deny a call"
    )
```

You cannot accidentally attach enforcement to something that only steers.

Two rule shapes cover the checkable cases:

- **single-call** ("never `npm`, use `pnpm`") to a PreToolUse deny, or a clean `rewrite` that swaps the field to the corrected value.
- **trajectory** ("tests must run before you claim success") to a Stop hook that blocks finishing when the required tool call never happened.

### Judgment rules: deterministic gate, fuzzy verdict

"Do not leave stub code" is where knowing-when-to-trust-the-model gets explicit. The gate is deterministic: the Stop hook fires every turn, so timing and triggering never depend on the model. Whether the standard was met is a fuzzy question no regex answers, so a cheap Haiku `{ok, reason}` verdict decides it *at* the deterministic gate. Three properties keep this honest:

- The verdict prompt is stored on the card, so the judgment is auditable.
- A relevance gate skips the model call entirely on turns where the rule can't apply (a code-quality rule is asked only when code was edited).
- The verdict path is lazy-loaded and **fails open**: a missing API key or a model hiccup never blocks you from finishing a session.

The determinism lives in the gate; the model is used only for the part that genuinely needs a judgment.

## Artifacts: 3 shipped, 6 sequenced

The vocabulary is nine artifact types. This is a sequenced roadmap, not nine working features.

| # | Type | Tier | Compiles to | Status |
|---|------|------|-------------|--------|
| 1 | Rule | HARD | hooks (PreToolUse / Stop / UserPromptSubmit) + `permissions.deny` | **shipped** |
| 2 | Knowledge note | SOFT (recall) | Precept-native FTS5/BM25 index, injected on relevance | **shipped** |
| 3 | Convention (rules-file) | SOFT | Precept-owned `.claude/rules/*.md` (global / repo / path-scoped) | **shipped** |
| --- | --- | --- | --- | --- |
| 4 | Skill | SOFT | `.claude/skills/<name>/SKILL.md` | designed |
| 5 | Agent persona | HARD (tools) + SOFT (prompt) | `.claude/agents/<name>.md` | designed |
| 6 | Output style | SOFT | `.claude/output-styles/<name>.md` | designed |
| 7 | Slash command | SOFT | `.claude/commands` or `.claude/skills` | designed |
| 8 | MCP / tool config | config | `.mcp.json` / `mcpServers` | designed |
| 9 | Permission profile | HARD | `settings.json` `permissions` | partial (import + clean-ban write-back) |

The six sequenced types ride the same `Lesson` spine and the same keep/veto gate; only their COMMIT target differs.

## How I measured it

Two tiers, separated deliberately, because they answer different questions and deserve different levels of trust.

**Tier 1: a deterministic confusion matrix.** `precept evals` runs the real enforcement matcher over a committed golden set of 25 cases (each carries its compiled policies, a tool call or inline Stop transcript, and the expected block/allow), and tallies TP/FP/TN/FN. Zero LLM, zero variance, CI-gateable with `--strict`.

```
                 predicted block   predicted allow
actual violation      TP = 10          FN = 0
actual compliant      FP = 0           TN = 15

recall (violations caught):     100%   (10/10)
false-block rate (compliant):     0%   (0/15)
```

The claim is bounded: of the violations it has a rule for, it blocks 100%, and it blocks zero compliant calls. Recall is over the deterministic subset, not over all possible mistakes.

**Tier 2: a paired before/after with a confidence interval.** The live corrected-behavior-rate delta (enforcement on vs off) is reported as a paired, multi-trial delta with a 95% CI, not a single number. Anthropic's own "Adding Error Bars to Evals" work shows infra noise alone swings agentic eval scores by several points, so an unpaired point estimate is not defensible. `evals/live.py` runs paired (same task, seed, machine), computes the mean delta and a 95% half-width, and states the noise floor. The deterministic Tier-1 number stays the headline; the live delta is the demo, reported with its error bars attached.

## How this relates to Claude Code native memory

Claude Code has an auto-memory that self-writes notes from corrections. That overlaps Precept's SOFT surface, and I will say so plainly: Anthropic could ship "promote this memory to an enforced rule" and subsume part of this.

What survives that is the specific move Precept is built around: compiling the checkable subset of a correction into a blocking hook behind a human keep/veto gate, with the HARD/SOFT boundary enforced in the type system rather than asserted in prose. The typed catalog, the earned-determinism COMPILE step, the deterministic-gate-plus-fuzzy-verdict pattern for judgment rules, and the eval methodology are the durable parts. A memory that notes and a hook that blocks are different tiers of trust, and that distinction is the product.

## Design principles

- **Rules are data, never code.** `enforce.py` is a fixed stdlib interpreter over compiled JSON. There is no `eval` or `exec` anywhere in the enforcement path. LLM-generated regex is length-capped and fails safe on `re.error` (a bad pattern matches nothing, it never crashes the hook).
- **Local-first, sync-safe.** Markdown cards are the source of truth and are safe in a synced vault. The derived SQLite index and policy cache live on local disk (`~/.local/state/precept`), never a cloud-synced folder, because SQLite corrupts under iCloud/Dropbox/NFS sync. The cache is disposable and fully rebuildable from the markdown.
- **Atomic writes, exact-inverse uninstall.** Every write to your real `~/.claude` is atomic (temp in the same dir, fsync, `os.replace`, with a `.bak`). Sidecar manifests record exactly what Precept wrote, so uninstall strips only Precept's own entries and never touches your rules. It is safe to run against a real `~/.claude`.
- **Cedar/OPA-style precedence.** Decision resolution is `deny > ask > rewrite > allow`; no match means allow. Arrived at independently; matches OPA, Cedar, and Microsoft's Agent Governance Toolkit.
- **Fail-closed detect, fail-open enforce.** The load-bearing asymmetry, restated once because everything depends on it.

Precept also ran an explicit conformance audit of itself against Anthropic's own published guidance for creating, retrieving, and configuring agent rules (`docs/ANTHROPIC-CONFORMANCE.md`). Strong conformance on configuring (the HARD/SOFT split, the hook contract, permission precedence, the Bash-arg-bypass handling) and on creating rules (positive-instruction extraction, the review gate as the "would removing this cause a mistake?" test). One honest open gap on retrieval: global conventions load always-on rather than just-in-time, which is roadmapped. See `DECISIONS.md` for the engineering decisions with their reasons.

## Quickstart

```bash
git clone https://github.com/NoaBarzelay/precept && cd precept
uv venv && uv pip install -e ".[dev]"
pytest -q            # 250 tests, fully offline/hermetic (LLM seams are injectable)

precept install                 # wire Precept's hooks into ~/.claude (idempotent, atomic, backed up)
precept bootstrap               # seed PENDING lessons from your setup: permission rules -> ready-to-enforce, CLAUDE.md -> soft
precept detect <transcript>     # classify a session; mint a PENDING lesson from a correction
precept list                    # see the catalog
precept keep <id>               # the human gate: PENDING -> ACTIVE; deterministic ones auto-compile
precept evals                   # the deterministic scorecard (100% recall, 0 false-blocks)
precept doctor                  # resolved paths + the sync-safety check + hook reachability
```

The learning loop (DETECT, COMPILE, judgment verdicts) needs a model, and there are two backends (`precept/inference.py`, selected by `PRECEPT_INFERENCE`). The default (`auto`) uses your Claude subscription through the local `claude` CLI when it is available and no API key is set: mint a one-time token with `claude setup-token`, export it as `CLAUDE_CODE_OAUTH_TOKEN`, and the flows run on your plan. Set `PRECEPT_INFERENCE=sdk` (with a billed `ANTHROPIC_API_KEY`) to use the raw Anthropic SDK instead. The client is injected at every seam (a `FakeClient` in the tests), so all 250 tests run offline. The **enforcement engine itself runs with zero LLM.** Detection and compilation need a model; blocking a tool call at runtime does not, which is why the hot path is stdlib-only and fast.

## Status

Early, but the core loop is real and tested: correct, detect, keep, block, with 250 hermetic tests and a CI-gated deterministic eval. The three shipped artifacts work end to end; the other six are designed and sequenced.

The full planned direction, the ReDoS and compile-fidelity hardening, the live paired-eval wiring, semantic recall behind a Recall@k gate, and the remaining six artifact types, is in [`ROADMAP.md`](ROADMAP.md).

## License

MIT.
