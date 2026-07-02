# Architecture

A map of the codebase so a reader can navigate it without reading all of it. Precept is a local-first Python CLI plus a set of Claude Code hooks. The authoring path (DETECT, COMPILE, review) uses a model; the enforcement path is pure stdlib and runs on every tool call.

## Data flow

```
   a Claude Code session
        |
        |  Stop / SessionEnd hook (hooks.py, fail-CLOSED)
        v
   DETECT (detect.py)          a small model reads genuine user turns and drafts a
        |                      candidate Lesson; abstains by default.
        v
   COMPILE (synthesize.py)     the Lesson becomes 1..N typed Policy objects (models.py).
        |                      Determinism is EARNED here: a matcher that passes the typed
        |                      validator, or the entity stays soft. Model output is data,
        |                      never code; regex is ReDoS-checked (safe_regex.py).
        v
   REVIEW (cli.py)             `precept keep` / `precept delete`. Nothing takes effect
        |                      until kept.
        v
   COMMIT                      the entity is a markdown card in ~/.precept (source of truth).
        |                      compile.py builds the derived policies.json cache from the cards.
        v
   ENFORCE (enforce.py)        PreToolUse / Stop / UserPromptSubmit hooks read the JSON
                               cache and decide. Stdlib only, no model, fail-OPEN.
```

The Data pillar (knowledge notes) rides the same review gate but commits to a local SQLite index instead of the policy cache, and is surfaced by relevance at prompt time (knowledge/retrieval.py).

## Module map

### Enforcement core (the hot path, stdlib only)
| File | Responsibility |
|------|----------------|
| `precept/enforce.py` | A fixed, hardened interpreter over the compiled policy JSON. Matches tool calls, resolves `deny > ask > rewrite > allow`, decides. No `eval`/`exec`. |
| `precept/safe_regex.py` | ReDoS protection for model-authored regex: reject catastrophic patterns at compile, bound every match at runtime. |
| `precept/judge.py` | The model verdict for judgment-kind rules, lazy-imported by `enforce` only when a judgment policy is present, and fail-open. |
| `precept/adapters/claude_code.py` | The Claude Code hook wire-format (read event, emit decision). Stdlib only; the one place that knows the host contract. |

### Types
| File | Responsibility |
|------|----------------|
| `precept/models.py` | The typed spine: Lesson, Policy, Condition, Match, and the enums. Validators enforce the invariants (a HARD tier cannot attach to a non-blockable event; a catastrophic regex is rejected). |

### Pipeline (the self-improving loop)
| File | Responsibility |
|------|----------------|
| `precept/detect.py` | DETECT: turn a real correction in a transcript into a PENDING Lesson (provenance-gated, abstain-aware). |
| `precept/synthesize.py` | COMPILE: synthesize a Lesson into an enforcing Policy, or leave it soft. |
| `precept/compile.py` | Build the plain-JSON policy cache from the markdown catalog (the form the hot path reads). |
| `precept/governance.py` | Rule governance: decay, supersede, conflict detection. |

### Entities and hosts
| File | Responsibility |
|------|----------------|
| `precept/hooks.py` | The console-script entrypoints Claude Code invokes (PreToolUse, Stop, UserPromptSubmit, SessionStart, SessionEnd). Thin, fast, fail-open. |
| `precept/install.py` | `precept install` / `uninstall`: wire the hooks into `~/.claude/settings.json` atomically, with exact-inverse removal. |
| `precept/inference.py` | The pluggable model backend for the AI seams (Claude subscription via CLI, or the SDK, or an injected fake in tests). |
| `precept/convention.py` | COMMIT target for the convention entity: write a kept convention into a `.claude/rules` file. |
| `precept/bootstrap.py` | Phase 0: seed the catalog from the user's existing setup. |

### Data pillar (knowledge)
| File | Responsibility |
|------|----------------|
| `precept/knowledge/store.py` | The one knowledge store over the markdown notes. |
| `precept/knowledge/index.py` | A derived, rebuildable SQLite FTS index over the notes. |
| `precept/knowledge/retrieval.py` | Surface relevant knowledge as `additionalContext` at prompt time. |
| `precept/knowledge/capture.py`, `audit.py`, `ops.py`, `config.py`, `conventions.py`, `frontmatter.py` | Capture new knowledge, audit integrity, scheduled ops, path config, structure rules, frontmatter helpers. |

### Paths, ops, measurement
| File | Responsibility |
|------|----------------|
| `precept/paths.py` | Path resolution and the critical local-first split (markdown catalog is sync-safe; the SQLite index and cache stay on local disk). |
| `precept/telemetry.py` | Tool-call event log and the weekly scorecard. |
| `precept/meter.py` | Token metering: capture and price each model flow's usage. |
| `precept/health.py` | The `doctor` health reminders. |
| `precept/evals/harness.py` | Tier-1 deterministic confusion-matrix eval over the golden set. |
| `precept/evals/live.py` | Tier-2 paired before/after behavior delta with a 95% CI. |
| `precept/evals/tokens.py` | Token-consumption eval (static ledger + live meter). |

## The enforcement hot path

On every guarded tool call and every Stop, Claude Code runs a `precept-hook-*` entrypoint (`hooks.py`), which reads the event via the adapter, calls `enforce.py` over the compiled `policies.json`, and emits a decision. This path makes no model call, touches only local files, and fails open: any missing file, unreadable cache, or unexpected error results in "allow" rather than a wedged session. A judgment rule is the one exception that consults a model (`judge.py`), at a deterministic gate, and it too fails open.

## Key seams

- **Inference backend** (`inference.py`): the model client is chosen by `PRECEPT_INFERENCE` and injected at every AI seam, so the whole suite runs offline against a fake client.
- **HARD/SOFT boundary** (`models.py`): enforced in the type system, not asserted, so an entity cannot claim enforcement it cannot deliver. `Policy._shape_matches_kind` rejects a HARD tier on any event that cannot block:

  ```python
  if self.enforcement_tier is Tier.HARD and self.hook_event not in BLOCKABLE_EVENTS:
      raise ValueError(
          f"HARD tier requires a blockable event; {self.hook_event} cannot deny a call"
      )
  ```

- **Judgment gate** (`judge.py`): an invariant with no mechanical check ("no stub code") runs a model verdict at a deterministic gate. The Stop hook fires every turn (timing never depends on the model); a cheap structured `{ok, reason}` verdict decides at that gate. The verdict prompt is stored on the entity's card (auditable), a relevance gate skips the call on turns where the rule cannot apply, and the path fails open: a missing key or model error never blocks a session.
- **Host adapter** (`adapters/claude_code.py`): the only module that knows the Claude Code hook contract, so a second host is an adapter, not a rewrite.
- **Local-first split** (`paths.py`): the markdown catalog is the source of truth and is sync-safe; the derived SQLite index and policy cache are local-only because SQLite corrupts under cloud sync.

## Where to start reading

1. `precept/enforce.py`: the runtime, and the clearest statement of what enforcement is.
2. `precept/models.py`: the types and the invariants they hold.
3. `precept/synthesize.py`: how a correction earns determinism.
4. `precept/hooks.py`: how the whole thing attaches to Claude Code.
