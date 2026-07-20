# AGENTS.md

Instructions for coding agents working in this repository. Precept is a TypeScript-on-Bun tool; the implementation lives entirely in [`ts/`](ts/). (It was rebuilt from a Python original, now removed; git history holds the reference.)

## Setup

```bash
cd ts && bun install
```

## Verify before claiming success

```bash
cd ts
bun test          # full suite, offline; must all pass (includes the repo privacy gate)
bun run typecheck # tsc --noEmit
bun run arch      # the dependency-rule fitness function
```

The suite is hermetic and offline: leaving `PRECEPT_INFERENCE` unset forces the inference layer down its abstaining path, and model clients are injected (`FakeClient`), so nothing reaches a live model.

## Invariants (do not break)

- **The interception hot path imports nothing heavy.** `interception.ts` and what it pulls in (`host`, `domain`, `record`, the compiled projection) may not import `infer`, `gate`, `retrieve`, a parser, or a schema library, and may not call a model or the network. Enforced by `test/arch.test.ts`.
- **Runtime fails open; detection abstains.** No error, missing backend, or unreadable cache may block a session; every session-time entrypoint returns the fail-open shape and records a fault. Detection returns null (abstains) rather than guessing.
- **Model output is data, never code.** No `eval`/`exec`; a model result is validated against a flat schema and dropped on any mismatch. The check language is a closed formula evaluated by a pure total evaluator (the regex op is a linear-time NFA, no backtracking).
- **Writes are atomic and reversible.** Cards and `settings.json` are written temp-then-rename; `install` self-marks its hook commands (`PRECEPT_MANAGED=1`) so `uninstall` is an exact inverse and leaves the user's own hooks untouched.
- **Nothing enforces without a keep.** The review gate (`precept keep`) is the trust boundary; never bypass or auto-approve. Only a user-typed turn may source a blocking entry (the provenance gate).
- **The privacy boundary is absolute.** Learned content (catalog cards from `~/.precept`, state, vault content, the user's personal rules or style) must never be committed to this public repository. `ts/test/privacy.test.ts` gates this in CI; never weaken it. Keep fixtures and docs free of machine-specific markers (use `/work/...`, never `/Users/<name>/`).

## Layout

- `ts/src/domain` the entry model, check language and evaluator, validity, lifecycle, currency (imports nothing).
- `ts/src/store` on-disk card layout, atomic writes, the frontmatter contract, paths.
- `ts/src/retrieve` FTS index, rank, budget, assemble the injected slice.
- `ts/src/host` the Claude Code contract: hook-event parsing, transcript reading, install.
- `ts/src/infer` the model backend (the only module that reaches the network), detection, the cost gate.
- `ts/src/gate` the human review gate. `ts/src/record` evidence, decisions, history, faults, queue. `ts/src/projection` the compiled check cache.
- Entrypoints (hook binaries) directly in `ts/src/`: `interception.ts` (PreToolUse), `injection.ts` (SessionStart/UserPromptSubmit), `observation.ts` (PostToolUse/SessionEnd), `cli.ts`.
- Build status and the pickup list: [ts/STATUS.md](ts/STATUS.md). Deferred work: [ROADMAP.md](ROADMAP.md). Design: [ARCHITECTURE.md](ARCHITECTURE.md), [DECISIONS.md](DECISIONS.md). Module map + dependency rule: [ts/README.md](ts/README.md).

## Docs conventions

Plain markdown, spec register, no em dashes. The README is a product spec; keep claims bounded and statuses honest (built / partial / designed / planned).

## Gotchas

- Inference on a subscription goes through the `claude` CLI backend (`PRECEPT_INFERENCE=cli`); never pass an OAuth token to a raw SDK. Unset, the loop records evidence but proposes nothing.
- The hooks run the entrypoints by absolute path (`bun /abs/.../observation.ts`); moving the repo breaks the registered commands until `precept install` is re-run.
- Run `git branch --show-current` before every commit; commit to `main` (the repo's history).
