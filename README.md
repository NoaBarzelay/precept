# Precept

Precept is a tool for Claude Code that converts user corrections into enforced configuration. Corrections that are mechanically checkable are compiled into Claude Code hooks that block a disallowed action (deny a tool call, block a Stop). Corrections that are not checkable are stored as context artifacts that steer but do not block. No artifact takes effect until the user approves it.

## Overview

Claude Code exposes two kinds of configuration:

- **Context configuration** (`CLAUDE.md`, skills, rules files) is delivered to the model as text and is followed at the model's discretion. Claude Code's documentation describes these as context, with no strict-compliance guarantee.
- **Deterministic configuration** (hooks, permission rules, subagent tool-scoping) is executed by Claude Code outside the model's control.

Precept classifies each correction and routes it to the correct layer. A checkable correction ("never run `npm`, use `pnpm`") becomes deterministic enforcement. A non-checkable correction ("do not leave stub code") becomes a context artifact or a gated model verdict. The boundary between the two tiers is enforced in the type system rather than asserted in prose.

## Problem

Agent memory records a correction and then complies with it inconsistently, in practice on a majority of turns rather than all of them. This is acceptable for preferences and unacceptable for invariants. The cause is structural, not a tuning gap: context configuration carries no compliance guarantee, and the only layer Claude Code runs deterministically is hooks. Precept closes the gap between where a correction is expressed (context, soft) and where it can be enforced (hooks, hard).

## Concepts

- **Lesson**: one correction captured as auditable data, stored as a markdown card. The source of truth.
- **Policy**: a typed enforcement unit compiled from a Lesson. One Lesson compiles to zero or more Policies.
- **Tier**: every artifact is HARD or SOFT. HARD blocks; SOFT steers. The tier is validated when the Policy is constructed.
- **Artifact type**: the configuration target a Lesson compiles to. Nine types are defined; three are implemented (see Artifact types).

## Pipeline

```
session transcript
      |  Stop / SessionEnd hook (fire-and-forget, fail-CLOSED)
      v
   DETECT   Haiku structured extraction -> MaybeLesson.
            Reads only genuine user-typed turns (provenance gate); abstains by default.
      v
   COMPILE  Lesson -> 1..N typed Policy (Cedar-style precedence).
            Determinism is earned here: a structured matcher that passes a typed
            validator, or the Lesson stays soft. The model does not assert enforceability.
      v
   REVIEW   `precept keep` / `precept delete`. Human gate; nothing enforces until kept.
            PENDING -> ACTIVE.
      v
   COMMIT   markdown card is the source of truth (plain text, diffable, sync-safe);
            compiled policies.json is the disposable cache, rebuildable from cards.
      v
   ENFORCE  PreToolUse / Stop / UserPromptSubmit hooks read the JSON cache.
            Stdlib only, no model call, fast.
```

DETECT fails closed (abstains rather than guess a false Lesson). ENFORCE fails open (a missing key, an unreadable cache, or an unrecognized transcript shape never blocks a session). Detection is conservative about what it learns; enforcement is conservative about what it breaks.

## Enforcement model

Every artifact is labeled HARD or SOFT, and enforcement is claimed only for the HARD tier.

- **HARD** is three mechanisms Claude Code runs without the model's cooperation: hooks (PreToolUse deny, Stop block, UserPromptSubmit block), the `permissions` `deny` array in `settings.json`, and subagent tool-scoping.
- **SOFT** is everything delivered as context: knowledge notes, conventions, skills, output styles. Precept writes the artifact correctly and atomically; it does not claim the model will obey it.

The boundary is encoded in the type system. `Policy._shape_matches_kind` in `models.py` rejects a HARD tier attached to an event that cannot block:

```python
if self.enforcement_tier is Tier.HARD and self.hook_event not in BLOCKABLE_EVENTS:
    raise ValueError(
        f"HARD tier requires a blockable event; {self.hook_event} cannot deny a call"
    )
```

A Policy that claims enforcement it cannot deliver fails to construct.

### Rule shapes

- **single-call**: a condition over one tool call ("never `npm`") compiles to a PreToolUse deny, or to a `rewrite` that swaps the field to the corrected value.
- **trajectory**: a condition over the session ("tests must run before claiming success") compiles to a Stop hook that blocks finishing when the required call never happened.

### Judgment rules

A correction with no mechanical check ("do not leave stub code") uses a deterministic gate with a model verdict. The Stop hook fires every turn (timing and triggering are deterministic). At that gate, a Haiku call returns a structured `{ok, reason}`. Three properties bound this:

- The verdict prompt is stored on the card, so the judgment is auditable.
- A relevance gate skips the model call on turns where the rule cannot apply (a code-quality rule runs only when code was edited).
- The verdict path is lazy-loaded and fails open: a missing key or a model error never blocks a session.

## Artifact types

Nine types are defined. Three are implemented; the other six ride the same Lesson spine and keep/veto gate and differ only in their COMMIT target.

| # | Type | Tier | Compiles to | Status |
|---|------|------|-------------|--------|
| 1 | Rule | HARD | hooks (PreToolUse / Stop / UserPromptSubmit) + `permissions.deny` | implemented |
| 2 | Knowledge note | SOFT (recall) | Precept-native FTS5/BM25 index, injected on relevance | implemented |
| 3 | Convention (rules-file) | SOFT | Precept-owned `.claude/rules/*.md` (global / repo / path-scoped) | implemented |
| 4 | Skill | SOFT | `.claude/skills/<name>/SKILL.md` | designed |
| 5 | Agent persona | HARD (tools) + SOFT (prompt) | `.claude/agents/<name>.md` | designed |
| 6 | Output style | SOFT | `.claude/output-styles/<name>.md` | designed |
| 7 | Slash command | SOFT | `.claude/commands` or `.claude/skills` | designed |
| 8 | MCP / tool config | config | `.mcp.json` / `mcpServers` | designed |
| 9 | Permission profile | HARD | `settings.json` `permissions` | partial (import + clean-ban write-back) |

## Evaluation

Two evaluation tiers measure different properties.

**Tier 1: deterministic confusion matrix.** `precept evals` runs the enforcement matcher over a committed golden set of 25 cases (each carries its compiled policies, a tool call or inline Stop transcript, and the expected decision) and tallies TP/FP/TN/FN. No model call, no variance, CI-gateable with `--strict`.

```
                 predicted block   predicted allow
actual violation      TP = 10          FN = 0
actual compliant      FP = 0           TN = 15

recall (violations caught):     100%   (10/10)
false-block rate (compliant):     0%   (0/15)
```

The claim is bounded: of the violations it has a rule for, it blocks all of them, and it blocks no compliant calls. Recall is measured over the deterministic subset, not over all possible mistakes.

**Tier 2: paired before/after with a confidence interval.** The live corrected-behavior-rate delta (enforcement on vs off) is reported as a paired, multi-trial delta with a 95% CI, not a single number, because agentic-eval infrastructure noise alone shifts scores by several points between identical runs (see Anthropic's "Adding Error Bars to Evals"). `evals/live.py` runs paired trials (same task, seed, machine), computes the mean delta and a 95% half-width, and reports the noise floor. The harness is built; wiring it to live agent runs is pending (see `ROADMAP.md`).

## Design principles

- **Rules are data, never code.** `enforce.py` is a fixed stdlib interpreter over compiled JSON. There is no `eval` or `exec` in the enforcement path. Model-generated regex is length-capped and fails safe on `re.error` (a bad pattern matches nothing; it never crashes the hook).
- **Local-first, sync-safe.** Markdown cards are the source of truth and are safe in a synced vault. The derived SQLite index and policy cache live on local disk (`~/.local/state/precept`), never a cloud-synced folder, because SQLite corrupts under sync. The cache is disposable and rebuildable from the markdown.
- **Atomic writes, exact-inverse uninstall.** Every write to `~/.claude` is atomic (temp in the same dir, fsync, `os.replace`, with a `.bak`). Sidecar manifests record what Precept wrote, so uninstall strips only Precept's own entries.
- **Cedar/OPA-style precedence.** Decision resolution is `deny > ask > rewrite > allow`; no match means allow. Matches OPA, Cedar, and Microsoft's Agent Governance Toolkit.
- **Fail-closed detect, fail-open enforce.**

A self-audit against Anthropic's published guidance for creating, retrieving, and configuring agent rules is in `docs/ANTHROPIC-CONFORMANCE.md`. It records strong conformance on configuration and creation, and one open gap on retrieval (global conventions load always-on rather than just-in-time), which is roadmapped.

## Installation

```bash
git clone https://github.com/NoaBarzelay/precept && cd precept
uv venv && uv pip install -e ".[dev]"
pytest -q            # 250 tests, offline and hermetic (model seams are injectable)

precept install                 # wire hooks into ~/.claude (idempotent, atomic, backed up)
precept bootstrap               # seed PENDING lessons from existing setup (permission rules, CLAUDE.md)
precept detect <transcript>     # classify a session; mint a PENDING lesson from a correction
precept list                    # show the catalog
precept keep <id>               # human gate: PENDING -> ACTIVE; deterministic lessons auto-compile
precept evals                   # deterministic scorecard
precept doctor                  # resolved paths, sync-safety check, hook reachability
```

## Requirements

The enforcement engine runs with no model. The learning loop (DETECT, COMPILE, judgment verdicts) requires a model, selected by `PRECEPT_INFERENCE` in `precept/inference.py`:

- Default (`auto`): the Claude subscription through the local `claude` CLI when it is present and no API key is set. Mint a token with `claude setup-token`, export it as `CLAUDE_CODE_OAUTH_TOKEN`.
- `sdk`: the Anthropic SDK with a billed `ANTHROPIC_API_KEY`.

The client is injected at every seam (a `FakeClient` in the tests), so all 250 tests run offline.

## Status

The core loop is implemented and tested (correct, detect, keep, block), with 250 hermetic tests and a CI-gated deterministic eval. The three implemented artifact types work end to end; the other six are designed. Built with Claude Code.

## Repository guide

- `DECISIONS.md`: the load-bearing engineering decisions with their reasons.
- `ROADMAP.md`: planned direction (hardening, coverage, the remaining artifact types).
- `precept/enforce.py`: the enforcement interpreter.
- `docs/ANTHROPIC-CONFORMANCE.md`: the self-audit and the one open gap.

## License

MIT.
