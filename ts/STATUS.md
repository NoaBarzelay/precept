# Build status (STATUS.md)

State of the build so another session can continue it. The product spec is [../README.md](../README.md), the design is [../ARCHITECTURE.md](../ARCHITECTURE.md), the decisions are [../DECISIONS.md](../DECISIONS.md), the deferred work is [../ROADMAP.md](../ROADMAP.md), and the module map is [README.md](README.md).

The TypeScript build is now the whole system: it is installed as the live Claude Code hooks, and the original Python was removed. CI runs the TypeScript suite.

As of this writing: **172 tests passing, offline; `tsc --noEmit` clean; the dependency-rule and interception fitness functions green; CI green.**

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
- `PRECEPT_INFERENCE=cli` selects the real `claude -p` backend; unset, the loop records evidence but proposes nothing, and SessionEnd does not auto-detect.

One hard rule when committing here: **the repo-privacy CI gate (`test/privacy.test.ts`) scans tracked text files** for machine-specific markers (`/Users/<name>/`, phone numbers, the vault mount). Keep fixtures, code, and docs neutral (use `/work/...`), or CI fails.

## What is built (17 batches)

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
| Transcript reader | `host/transcript`, `observation` (SessionEnd), cli `ingest` | Read a finished session transcript, draft evidence: a verbatim window of surrounding turns per human-typed turn (provenance gate on the transcript's own shape), and a kind-aware silent-edit diff (full `Write` by equality, `Edit`/`MultiEdit`/`NotebookEdit` fragment by presence, agent output vs disk state, R1.1). Content-derived evidence ids + id-dedup make a re-fired SessionEnd idempotent (no cursor), robust to a compacted/rotated transcript. This closes the automatic-learning loop: evidence is now self-produced, not only fed. |
| Install | `host/install`, cli `install`/`uninstall` | Register the entrypoints in `~/.claude/settings.json`: interception on PreToolUse (`*`), injection on SessionStart/UserPromptSubmit, observation on PostToolUse/SessionEnd. Commands run as `bun <abs entrypoint>` prefixed with a `PRECEPT_MANAGED=1` self-marker, so entries are identifiable in-place with no custom keys, install is idempotent, and uninstall is the exact inverse (N8). Atomic write with `.bak`, preserves the user's own hooks, settings path env-overridable for hermetic tests. This is what attaches Precept to Claude Code in real use, so the four hooks now fire on their own. |
| Detect cost gate | `infer/prefilter`, `infer/detect` | A cheap, recall-biased pre-filter before the model (Risk 5, R1.18): corrections/silent-edits/stated-knowledge/agent-research always propose; a plain instruction proposes only on durable cues (always/never/use/prefer/...), so a one-off task turn spends no call. Filtered evidence stays in the append-only log for the R1.14 hindsight pass. `detect` returns queued/proposed/filtered counts. |
| Currency (part 1) | `domain/entry` (retire/supersede/isExpired), `domain/currency`, cli `retire`/`supersede` | Invalidate-not-delete governance (Risk 4). `retire` closes valid-time and drops the entry from the projection and index; `supersede` folds an entry over its successor, recording `supersededBy`. Review-time surfaces a lexical same-kind same-scope near-duplicate on `pending`/`keep` so the reviewer can supersede it (R1.4). Design note for the full surface (observable conditions, the sweep, override reconfirmation) is in DECISIONS.md. |
| Cutover | `observation` (auto-detect), `host/install`, CI | The TypeScript build is the live system: installed as the Claude Code hooks, Python removed, CI on Bun. On SessionEnd, when new evidence lands and the backend is enabled (`PRECEPT_INFERENCE=cli`), observation kicks `detect` in a detached background process so the review queue fills on its own (R1.1, R1.5; N4 gates the spend). The repo-privacy gate is a TS test (`test/privacy.test.ts`). |

Entrypoints (the hook binaries): `interception.ts` (PreToolUse), `injection.ts` (SessionStart/UserPromptSubmit), `observation.ts` (PostToolUse + SessionEnd, which also triggers background detection), `cli.ts`. All no-op under the `PRECEPT_INFERENCE_SUBPROCESS` sentinel (fork-bomb guard).

CLI commands: `install uninstall note recall list remove reindex compile confirm reject retire supersede firing ingest detect pending keep dismiss`.

## What is NOT built

The deferred work is documented in [../ROADMAP.md](../ROADMAP.md), each item mapped to its requirement or risk: currency part 2 (the `maintain` sweep, override reconfirmation), delta-to-inference feedback (R1.13), the turn-end judgment tier (R1.18), correction-to-check synthesis, the always-on convention writer (R1.7/R1.8), per-tool hook narrowing, full write-path CAS, and the tooling (eval harness, metering, doctor). The MCP server and a general observable-predicate language are explicitly dropped.

## Doc-vs-code honesty note

ARCHITECTURE.md is design intent, ahead of the code in places. DECISIONS.md's build-decisions section lists what the intent describes but the code does not yet implement (full CAS, rewrite outcome, git transaction-time, currency part 2). Keep that section, and ROADMAP.md, honest as you build.
