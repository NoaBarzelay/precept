# Language decision: TypeScript on Bun

Status: **decided, not implemented.** Precept is built in Python today. The move to TypeScript on Bun is the chosen direction and has not started. This document records the decision, the mid-2026 landscape it was made against, and the reasoning, so the choice can be challenged on its merits rather than taken on faith.

## Decision

Best-in-class for a Claude Code extension, as a single language: **TypeScript on Bun.**

- **Host-native.** Claude Code is itself a Node and TypeScript application, so an extension runs in the host's own ecosystem and consumes its SDK and types directly. This is the strongest answer to the project's largest dependency risk, the extension contract that has already changed once.
- **Fastest startup of the interpreted runtimes.** Bun cold-starts in 8 to 15 ms, ahead of Python (10 to 50 ms) and Node (60 to 120 ms). The enforcement hook pays startup on every guarded tool call.
- **Single-binary distribution.** Bun compiles to one executable, which erases the venv and pipx drift that has already bitten this project.
- **Built-in SQLite.** Bun ships SQLite, a clean fit for the catalog's derived index.
- **First-class AI SDK.** The Anthropic TypeScript SDK plus the mature Vercel AI SDK cover the learning loop, with runtime validation of model output via Zod, at parity with Python and pydantic.

The one real risk is **Bun's youth.** It reached production readiness in 2026 and is the newest of the runtimes, so occasional rough edges are expected. Node is the conservative fallback if Bun ever proves unstable, and the TypeScript code carries over to it unchanged.

## Why not stay on Python

Python is the close second, and the honest reason it does not win is narrow, not decisive. It keeps three real edges: the eval and statistics tooling (numpy and scipy; the paired before-and-after with a confidence interval is the number-one signal and is a few lines in Python), stdlib `ast` for parsing Python code in the structural matcher, and existing fluency. What tips it to TypeScript is that the highest-weight needs for this tool (distribution, host-nativeness, startup) all favor Bun, while the SDK and iteration speed are a tie. Python's edge is real but surmountable: a bootstrap confidence interval is a few lines in TypeScript too.

## Best-in-class, July 2026

The decision was made against the mid-2026 landscape, not older defaults.

- **Bun matured.** Bun 1.3 is production-ready with about 98% Node compatibility, 8 to 15 ms cold start, and single-executable compilation. It is reported that Claude Code itself ships as a Bun single-file executable; if so, that is the host validating this exact stack for this exact class of tool, but the decision does not rest on that single claim.
- **The TypeScript AI ecosystem caught up.** The Vercel AI SDK became a full agent platform (roughly 20 million downloads a month), so the learning loop is no longer a Python-only strength.
- **Python got faster and shed the GIL.** Python 3.14 makes free-threading official and cut the single-thread penalty to about 5 to 10%, keeping it best-in-class for the eval and statistics half.
- **Go and Rust remain best-in-class for a pure CLI binary,** and are the right answer only if the enforcement runtime, not the learning-and-eval loop, were the center of gravity.

## The characteristics, and why each matters here

Precept has four jobs, and each cares about different language characteristics: a **hot-path hook** (runs on every guarded tool call), a **learning loop** (LLM calls), an **eval harness** (statistics), and **distribution** (install and run). A characteristic matters only insofar as it touches one of these.

Plain definitions of the terms used below:

- **Startup time.** The delay from launching a process to your code running. Compiled binaries load in 1 to 5 ms; interpreters and VMs must initialize first.
- **Static vs dynamic typing.** Static (Go, Rust, TypeScript) checks that values are used consistently at compile time, before running; dynamic (Python, JavaScript) checks at run time. TypeScript's types are erased at runtime, so untrusted data (model output) still needs a runtime validator (Zod, or pydantic in Python).
- **Memory model.** Garbage collection (Python, Go, JS/TS) frees memory automatically; ownership (Rust) frees it deterministically at compile time with no GC. All of these are memory-safe.
- **Concurrency.** Doing many things at once. Python historically had the GIL (one thread at a time), now optional in 3.14; Go has goroutines; JS/TS use an async event loop; Rust has compile-checked concurrency.
- **Single-binary distribution.** One self-contained executable versus an interpreter plus a resolved dependency environment.
- **Host-nativeness.** Being written in the same language and runtime as Claude Code, so you share its SDK, types, and fixtures.

### Scorecard

Weight is how much each characteristic actually matters for Precept. Weighting by what the tool needs, not by which language wins in the abstract, is the whole point.

| Characteristic | Weight for Precept | Python | TypeScript (Bun) | Go | Rust |
|---|---|---|---|---|---|
| Startup (hook) | low (masked by model latency) | ok | very good | best | best |
| Static type strength | medium (the HARD/SOFT invariant) | runtime only | strong | medium | strongest |
| Memory model | negligible here | fine | fine | fine | best, unused |
| Concurrency | low to medium (I/O-bound) | good, now no-GIL | good (async) | best | best |
| Distribution | high (install, drift) | weak (venv) | strong (compile) | strong | strong |
| LLM SDK | high | best | best | ok | ok |
| Stats and eval | high (the number-one signal) | best | thin | thin | thin |
| AST and parsing | medium (matcher tier) | stdlib for Python | via tree-sitter | via tree-sitter | best |
| Host-nativeness | high (contract drift) | good | best | weak | weak |
| Runtime maturity | medium | best | newest, rough | best | best |
| Dev velocity | high (iterative tool) | best | best | good | weakest |

The decision falls out of the high-weight rows. Distribution, LLM SDK, stats and eval, host-nativeness, and dev velocity are the ones that matter for this tool. Two languages own them, Python and TypeScript, and they split them: TypeScript wins distribution and host-nativeness (and, on Bun, startup); Python wins stats and eval; they tie on the SDK and velocity. The low-weight rows (raw execution speed, memory model) are where compiled languages shine and where Precept does not care, which is why Go and Rust do not lead despite winning them.

### What each job wants

- **Hot-path hook:** fast startup and safety. Go, Rust, or Bun are ideal; Python and Node are acceptable because the hook runs beside a multi-second model turn, so tens of milliseconds is noise in practice.
- **Learning loop:** the LLM SDK and iteration speed. Python and TypeScript tie.
- **Eval harness:** statistics tooling. Python leads; the main thing a migration must port.
- **Distribution:** a single binary. Go, Rust, or Bun; not Python.

## Honest dissent

- **Stay on Python.** Its eval and statistics ecosystem is the number-one signal's home turf, and rewriting a working system is real cost for a benefit (distribution, host-nativeness) that a personal tool feels only mildly. A reasonable person could decline the migration on those grounds.
- **Split the architecture instead of choosing one language.** The theoretical optimum is a Bun or Rust hot-path enforcer and distributable binary, with a Python eval and statistics core. The rules-are-data design (the enforcer reads a JSON policy cache) makes this feasible without touching the learning loop. It is over-engineering for a single-user tool, but it is the honest optimum and a live option if only the enforcement runtime ever needs to move.

## What a migration would change

Recorded so the decision is concrete, not abstract:

- **The enforcement hot path** becomes a Bun-compiled binary, dropping Python interpreter startup and the venv install path.
- **The structural matcher's AST tier** shifts from Python's stdlib `ast` (zero dependency for Python code) to tree-sitter, which TypeScript would need for any language anyway. See DECISIONS.md, the matcher entry.
- **The eval and statistics harness** is the heaviest port: the confusion-matrix scorecard is trivial anywhere, but the paired before-and-after with a confidence interval must be reimplemented (a bootstrap CI, a few lines, but new).
- **The catalog** moves from Python `sqlite3` to Bun's built-in SQLite; markdown cards stay the source of truth and are language-agnostic.
- **Distribution** moves from pipx and uv to a single compiled executable.

Nothing above is started. This repository is Python until it is.

## Sources

- [Bun vs Node vs Deno, 2026 (Strapi)](https://strapi.io/blog/bun-vs-nodejs-performance-comparison-guide)
- [JavaScript runtime comparison, 2026 (DevToolLab)](https://devtoollab.com/blog/javascript-runtime-comparison)
- [Go vs Rust for CLI tools, 2026 (TechBytes)](https://techbytes.app/posts/go-vs-rust-cli-tools-performance-dx-guide-2026/)
- [Python 3.14 and the end of the GIL (Towards Data Science)](https://towardsdatascience.com/python-3-14-and-the-end-of-the-gil/)
- [Vercel AI SDK](https://github.com/vercel/ai)
- [AI agent framework comparison, 2026 (Speakeasy)](https://www.speakeasy.com/blog/ai-agent-framework-comparison/)
