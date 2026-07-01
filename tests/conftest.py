"""Shared test fixtures.

`_hermetic_precept_env` (autouse) points Precept's catalog, local state, and Claude config
at fresh per-test temp dirs, so NO test ever reads the developer's real `~/.precept`, the
local knowledge index, or `~/.claude`. Without this, `enforce.evaluate_userpromptsubmit`'s
retrieval injection (vault knowledge + retrieval_only conventions) leaks real machine state
into tests that assert a bare allow — the index lives under `state_dir()` and the catalog
under `precept_home()`, both isolated here.

`PRECEPT_VAULT` is pointed at an EMPTY temp dir (not the developer's real vault): otherwise
knowledge retrieval auto-builds an FTS index over the real vault on any non-blocked prompt,
which both leaks real content and adds seconds per test. Tests that need their own vault
`monkeypatch.setenv` over it; tests that assert the unset-vault error `monkeypatch.delenv`
it (both run after this fixture, so they win).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_precept_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "precept-home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "precept-state"))
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(tmp_path / "claude-home"))
    empty_vault = tmp_path / "empty-vault"
    empty_vault.mkdir()
    monkeypatch.setenv("PRECEPT_VAULT", str(empty_vault))
