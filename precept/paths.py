"""Where Precept keeps things — and the critical local-first split.

THE RULE (SQLite + cloud-sync = corruption, per SQLite's own howtocorrupt docs):
  - Markdown source-of-truth may live in a synced location (it's safe: whole-file
    atomic writes, git as history).
  - The derived SQLite index/state must live on a real LOCAL disk, OUTSIDE any
    iCloud/Dropbox/NFS path, because it's written incrementally and sync will
    corrupt it mid-write. It's disposable anyway (rebuildable from markdown).

Override any path with the matching PRECEPT_* env var (useful for tests).
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    return Path(raw).expanduser() if raw else default


def precept_home() -> Path:
    """Catalog of rule-cards + config. A real local dir (default ~/.precept),
    git-init'd for the audit log."""
    return _env_path("PRECEPT_HOME", Path.home() / ".precept")


def catalog_dir() -> Path:
    """Markdown rule-cards (the source of truth for RULE artifacts)."""
    return precept_home() / "catalog"


def notes_dir() -> Path:
    """Markdown knowledge notes (the source of truth for KNOWLEDGE artifacts)."""
    return precept_home() / "notes"


def state_dir() -> Path:
    """Derived/disposable state: the index .db, compiled policy cache, cursors.
    MUST be local (XDG_STATE_HOME or ~/.local/state), never the synced vault."""
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return _env_path("PRECEPT_STATE_DIR", base / "precept")


def policies_cache() -> Path:
    """The plain-JSON compiled policies the enforcement hot path reads (stdlib only)."""
    return state_dir() / "policies.json"


def index_db() -> Path:
    """The knowledge index (FTS5 [+ optional sqlite-vec]). Derived, local-only."""
    return state_dir() / "index.db"


def claude_home() -> Path:
    """The user's real Claude Code config dir — a COMMIT target."""
    return _env_path("PRECEPT_CLAUDE_HOME", Path.home() / ".claude")


def ensure_dirs() -> None:
    for d in (precept_home(), catalog_dir(), notes_dir(), state_dir()):
        d.mkdir(parents=True, exist_ok=True)
