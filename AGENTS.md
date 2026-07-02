# AGENTS.md

Instructions for coding agents working in this repository.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
```

## Verify before claiming success

```bash
ANTHROPIC_API_KEY= .venv/bin/python -m pytest -q          # full suite, offline; must all pass
ANTHROPIC_API_KEY= .venv/bin/python -m precept evals --strict   # deterministic eval gate
ruff check precept/ tests/
```

## Invariants (do not break)

- **The enforcement hot path is stdlib-only.** `enforce.py`, `adapters/`, and `safe_regex.py` may not gain third-party imports, model calls, or network access.
- **Runtime fails open; DETECT fails closed.** No error, missing key, or unreadable cache may ever block a session. Detection abstains rather than guesses.
- **Model output is data, never code.** No `eval`/`exec`. Regex from model output goes through `safe_regex` (compile-time rejection + bounded matching).
- **Writes to `~/.claude` are atomic and reversible.** Temp file in the same directory, fsync, `os.replace`, `.bak` backup, and a sidecar manifest so uninstall stays an exact inverse.
- **Tests are hermetic.** They must never read the real `~/.claude`, `~/.precept`, or a vault; `tests/conftest.py` isolates state per test. Model clients are injected (`FakeClient`), so the suite runs offline.
- **Nothing enforces without a keep.** The review gate (`precept keep`) is the trust boundary; never bypass or auto-approve.

## Terminology

An **entity** is the catalog record (rule, knowledge note, convention, skill, agent persona). An **artifact** is the compiled output an entity produces at its commit target; the code enum `ArtifactType` names the commit-target kind.

## Layout

- `precept/` core package: `enforce.py` (runtime), `models.py` (types), `detect.py` / `synthesize.py` / `compile.py` (pipeline), `hooks.py` (entrypoints), `inference.py` (model backend seam)
- `precept/knowledge/` the data pillar (index, retrieval, capture)
- `precept/adapters/` host wire formats (Claude Code)
- `precept/evals/` eval harnesses (deterministic golden set, paired live delta, tokens)
- `tests/` hermetic suite
- Design docs: `ARCHITECTURE.md`, `DECISIONS.md`, `ROADMAP.md`, `docs/ARTIFACTS.md`

## Docs conventions

Plain markdown, spec register, no em dashes. The README is a product spec; keep claims bounded and statuses honest (built / partial / designed / planned).

## Gotchas

- The installed copy (a pipx venv) is separate from this source tree; editing source changes nothing until reinstall: `uv pip install --force-reinstall --no-deps .` against that venv.
- Run `git branch --show-current` before every commit; parallel sessions have committed to the wrong branch in this repo before.
- Inference on a subscription must go through the `claude` CLI backend (`PRECEPT_INFERENCE=cli`); never pass an OAuth token to the raw `anthropic` SDK.
