# Precept

Precept is a personal, self-improving platform for agentic AI work. It defines and catalogs two things as typed artifacts: the processes you run with AI (how you work) and the entities and data those processes act on. It improves both continuously, from how you work and from its own reading of best practices, and it always proposes rather than acting silently. Deterministic enforcement is one capability within it: the process artifacts that are mechanically checkable compile into Claude Code hooks that block a disallowed action, not notes that nudge.

## Three pillars

- **Processes.** The workflows you run with AI, captured as typed artifacts: rules, conventions (`CLAUDE.md` and rules files), skills, agent personas, output styles, slash commands, MCP config, permission profiles. Some carry a HARD, enforced edge (rules, agent personas, permission profiles); the rest steer.
- **Entities and data.** What those processes act on. Today this is a knowledge catalog for recall; a typed entity catalog is the planned upgrade.
- **Self-improving.** A detect, review, compile loop authors and refines all of the above, from (a) how you work and (b) Precept's own autonomous learning (reading best practices and the web on its own judgment). It always proposes for human review and never acts silently.

## Why

Working with an agent produces a stream of corrections, preferences, and procedures worth keeping: how you want it to work, what it should and should not do, the facts and entities it operates on. Left in chat they evaporate; written into a single memory file they accrete unread and are followed inconsistently. Precept captures each one as a typed, reviewable artifact, routes it to the right home (a rule, a skill, an agent persona, a knowledge note), and keeps the catalog small and current.

For the subset of processes that are invariants rather than preferences ("never run `npm`", "run the tests before claiming success"), steering is not enough. Claude Code exposes two configuration layers: context (`CLAUDE.md`, skills, rules files), which the model follows at its discretion, and deterministic (hooks, permission rules, subagent tool-scoping), which Claude Code executes outside the model's control. Precept compiles the checkable invariants into the deterministic layer so they block rather than nudge, and enforces the boundary between the two tiers in the type system rather than asserting it in prose.

## Concepts

- **Lesson**: one correction captured as auditable data, stored as a markdown card. The source of truth.
- **Policy**: a typed enforcement unit compiled from a Lesson. One Lesson compiles to zero or more Policies.
- **Tier**: every artifact is HARD or SOFT. HARD blocks; SOFT steers. The tier is validated when the Policy is constructed.
- **Artifact type**: the configuration target a Lesson compiles to. Nine types are defined; three are implemented (see Artifact types).

## Pipeline

The self-improving loop that turns how you work into artifacts. It always proposes for human review and never acts silently.

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

Enforcement is one capability of the platform: the HARD, enforced edge on process artifacts. Every artifact is labeled HARD or SOFT, and enforcement is claimed only for the HARD tier.

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

Nine types are defined. They populate two of the three pillars, and the self-improving loop authors them: types 1 and 3 through 9 are Processes (how you work), and type 2 is the Entities-and-data catalog (a typed entity catalog is the planned upgrade). Three types are implemented; the other six ride the same Lesson spine and keep/veto gate and differ only in their COMMIT target.

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

## Security model

- **Footprint.** `precept install` registers five hooks in `~/.claude/settings.json` (PreToolUse, Stop, UserPromptSubmit, SessionStart, SessionEnd), each pointing at a `precept-hook-*` command. settings.json is backed up before every edit, and `precept uninstall` removes exactly those entries. State lives in `~/.precept` (the catalog) and `~/.local/state/precept` (the cache); both are local, and nothing is written to a synced folder.
- **Data egress.** The enforcement hooks are local stdlib checks and send nothing off the machine. The learning loop (DETECT, judgment verdicts) sends transcript excerpts and prompt text to the model for classification, through the local `claude` CLI on the subscription backend or the Anthropic API with a key, the same data path as any Claude Code turn. `PRECEPT_DISABLE_DETECT=1` disables the loop entirely and leaves enforcement running.
- **Model-authored logic never executes.** Matchers are data interpreted by a fixed stdlib engine: no `eval`, no `exec`, and regex is length-capped and fails safe. Nested inference is guarded by the `PRECEPT_SUBPROCESS` sentinel against recursion.
- **Review boundary.** Nothing is enforced until the user runs `precept keep`. Rules are readable markdown the user can inspect, edit, or delete at any time.

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
