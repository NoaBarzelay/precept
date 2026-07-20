# TypeScript rebuild: build status (STATUS.md)

State of the `ts/` rebuild so another session can continue it. The product spec is [../README.md](../README.md), the design is [../ARCHITECTURE.md](../ARCHITECTURE.md), the decisions are [../DECISIONS.md](../DECISIONS.md), and the module map is [README.md](README.md).

As of this writing: **118 tests passing, offline; `tsc --noEmit` clean; the dependency-rule and interception fitness functions green; CI (the Python reference suite) green.**

## How to resume

```
cd ts
bun install
bun test            # whole suite, offline against an injected fake model
bun run typecheck   # tsc --noEmit
bun run arch        # the dependency-rule fitness function
```

Env vars (all optional, defaulted, env-overridable so tests are hermetic):
- `PRECEPT_HOME` catalog root (markdown cards, source of truth). Default `~/.precept`.
- `PRECEPT_STATE_DIR` derived + operational state (index, logs, queue, projection). Default under `~/.local/state/precept`.
- `PRECEPT_INFERENCE=cli` selects the real `claude -p` backend; otherwise the loop abstains.

Two hard rules when committing here:
1. **The repo-privacy CI gate scans `ts/` text files** for machine-specific markers (`/Users/<name>/`, phone numbers, the vault mount). Keep fixtures and code neutral (use `/work/...`), or CI fails.
2. **A parallel session edits the Python source.** Stage only `ts/` and docs; never `git add` the Python files.

## What is built (12 batches)

| Area | Modules | Notes |
|---|---|---|
| Check language | `domain/{facts,check,regex,glob}` | Quantifier-free formula over a closed atom set; pure total evaluator; regex is a hand-rolled single-pass Thompson NFA (linear time, no backtracking, no re2 dep); glob is memoized. `checkError` validates the whole AST. |
| Entry model | `domain/entry` | Typed contract, bi-temporal `validity` (valid-time), `provenance`, `scope`, `tier`/`lifecycle`/`confirmations`, per-card `version` (CAS token). `entryError` is the frontmatter contract. `confirmOnce`/`narrowOnReject`, `canDeny`/`isLive`. |
| Store | `store/{paths,card,lock}` | Local-first split (catalog syncable, derived local-only). Cards = YAML frontmatter + a fenced ```check JSON block + prose; atomic crash-safe write; every read/write validated. `withCardLock` cross-process advisory lock. |
| Retrieve | `retrieve/{index,retrieve}` | SQLite FTS5 (`bun:sqlite`), section-granular (R2.7), validity-filtered (R2.8), stopwords, N9 budget (top 5 / 2000 chars, hard-truncated). |
| Write path | `domain/candidate`, `infer/{client,capture,detect}`, `record/{log,evidence,decision,history,fault,queue}`, `gate/gate` | evidence -> candidate -> review queue -> gate -> store. Abstention (R1.2/R2.2), provenance gate (only user-typed turns source hard rules), reachability gate (D3/N5), decision records (N6/N7), delta (R1.13 recorded not yet consumed). |
| Enforcement | `domain/enforce`, `projection/projection`, `interception.ts` | Compile live hard rules to a plain-JSON check cache (scope conjoined onto the check, R1.6); interception reads it, decides deny/ask/allow, fails open and records faults (N1). No model/parser/schema-lib on the path (fitness-enforced). |
| Probation | `domain/entry` (confirm/narrow), `store/lock`, cli | Probationary asks, graduates after 3 confirmations to deny, reject narrows+resets (R1.19-R1.21). |
| Evidence validation | `record/history`, `observation.ts`, `domain/validate`, cli `firing` | Tool-call history (PostToolUse); `reachable`/`firing`/`subsumes` over recorded traffic. |
| Live loop | `record/queue`, `infer/detect`, cli `detect`/`pending`/`keep`/`dismiss` | The learning loop runs end to end (fed evidence -> detect -> queue -> review -> catalog). |
| Real backend | `infer/cli_client` | `CliClient` shells `claude -p` with native structured output + recursion guard; injected `Runner` so it is offline-testable; live-only spawn. `makeClient` selects by `PRECEPT_INFERENCE`. |

Entrypoints (the hook binaries): `interception.ts` (PreToolUse), `injection.ts` (SessionStart/UserPromptSubmit), `observation.ts` (PostToolUse), `cli.ts`. All no-op under the `PRECEPT_INFERENCE_SUBPROCESS` sentinel (fork-bomb guard).

CLI commands: `note recall list remove reindex compile confirm reject firing detect pending keep dismiss`.

## What is NOT built (the pickup list, roughly in priority order)

1. **Transcript -> evidence reader.** The last piece for automatic learning. `detect` consumes `EvidenceRecord`s but nothing produces them from a live Claude Code session. Needs: read the session transcript, assemble evidence windows, and compute the silent-edit diff (agent output vs final file state) for R1.1. Wire it to a `SessionEnd` observation trigger. Until this exists, learning is fed, not self-running.
2. **Install / plugin packaging.** The hook binaries exist but nothing wires them into `~/.claude/settings.json`. Needs an `install`/`uninstall` that registers the four entrypoints (with the `--setting-sources` and sentinel env), atomically and with exact-inverse removal (N8). Without this the system does not attach to Claude Code in real use.
3. **Currency / governance sweeps** (R1.9-R1.12, R2.8-R2.11). `retired`/`superseded` statuses exist and are excluded from retrieval, but nothing transitions an entry into them. `validate.subsumes` is built but unused. Needs a scheduled maintenance path: validity sweep, supersede, conflict detection, override/divergence reconfirmation. This is the Risk-4 mitigation; currently `isLive`'s stale-exclusion is vacuous.
4. **Correcting the inference from deltas** (R1.13). `deltaBetween` is computed and stored in decision records; nothing feeds it back into `infer` (no exemplar/standing-instruction/calibration). Recording half only.
5. **Turn-end judgment tier** (R1.18, N13). A `Stop` entrypoint for structural checks (needs a parser, tree-sitter, off the hot path) and the model-verdict tier. Deferred by design.
6. **Full write-path CAS.** Only the lifecycle read-modify-write (`confirm`/`reject`) takes the lock and bumps `version`. `writeCard`/`gate.review` do a plain atomic rename with no version check, so two parallel writers (or the Python runtime during the strangler) can still clobber. Add the CAS check to `writeCard`.
7. **Always-on convention writer** (R1.7/R1.8). A convention that should load into `.claude/rules/` is never written there, and there is no always-on line cap. Injection covers knowledge; convention placement does not exist.
8. **Smaller:** `rewrite` outcome (engine is deny/ask/allow only, though DECISIONS keeps it as intended); git as transaction-time (asserted, not read by code); `SessionStart` injection (no-op, awaits the always-on set); a startup latency-budget test for N2.

## Doc-vs-code honesty note

ARCHITECTURE.md is design intent, ahead of the code in places. DECISIONS.md's last section ("Build decisions from the TypeScript rebuild") lists what the intent describes but the code does not yet implement (CAS, rewrite, git transaction-time, currency). Keep that section honest as you build.
