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
import re
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


def _session_slug(session_id: str) -> str:
    """A filesystem-safe slug for a session id (used in per-session cursor/lock
    filenames). Falls back to 'default' for an empty id so a session-less caller
    (e.g. a manual `precept detect`) still gets a stable, isolated cursor."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id or "").strip("-")
    return s[:128] or "default"


def cursors_dir() -> Path:
    """Per-session DETECT cursors (item 1): the last transcript offset already
    classified, so each Stop processes only NEW turns. Derived/disposable/local."""
    return state_dir() / "cursors"


def detect_cursor(session_id: str) -> Path:
    """The cursor file for one session (records the last processed transcript offset)."""
    return cursors_dir() / f"{_session_slug(session_id)}.json"


def detect_lock(session_id: str) -> Path:
    """A per-session DETECT lock (item 1) so two near-simultaneous Stop events don't
    double-classify the same turns. A directory created with os.mkdir (atomic) is the
    lock token; held briefly, stale locks are reclaimed. Derived/disposable/local."""
    return cursors_dir() / f"{_session_slug(session_id)}.lock"


def knowledge_audit_stamp() -> Path:
    """Timestamp of the last daily knowledge integrity audit (slice 2). A once-per-day
    THROTTLE reads/writes this so the audit can ride SessionStart without nagging.
    Derived/disposable/local (state dir, never the synced vault)."""
    return state_dir() / "knowledge_audit.stamp"


def managed_permissions_manifest() -> Path:
    """The set of settings.json permission strings Precept last wrote (item B). Lets a
    re-sync subtract ONLY Precept's own prior entries, never the user's. Local/derived."""
    return state_dir() / "managed_permissions.json"


def managed_conventions_manifest() -> Path:
    """The set of `.claude/rules/*.md` convention files Precept last wrote (the CONVENTION
    artifact). Lets a re-sync / uninstall delete ONLY files Precept created, never the
    user's own rules files. Local/derived/rebuildable."""
    return state_dir() / "managed_conventions.json"


def claude_home() -> Path:
    """The user's real Claude Code config dir — a COMMIT target."""
    return _env_path("PRECEPT_CLAUDE_HOME", Path.home() / ".claude")


def ensure_dirs() -> None:
    for d in (precept_home(), catalog_dir(), notes_dir(), state_dir(), cursors_dir()):
        d.mkdir(parents=True, exist_ok=True)
