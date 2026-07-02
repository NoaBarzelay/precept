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
    plain-text and diffable, so it can be kept under version control for a full history."""
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


def token_usage_log() -> Path:
    """Append-only JSONL meter of per-flow LLM token usage (meter.record writes it;
    `precept tokens` aggregates it). Derived/disposable/local — never the synced vault."""
    return state_dir() / "token_usage.jsonl"


def inference_health() -> Path:
    """Last inference failure per flow (inference.note_failure writes it; `precept doctor`
    reports it) — makes a total auth/config failure visible. Derived/disposable/local."""
    return state_dir() / "inference_health.json"


def knowledge_audit_stamp() -> Path:
    """Timestamp of the last daily knowledge integrity audit (slice 2). A once-per-day
    THROTTLE reads/writes this so the audit can ride SessionStart without nagging.
    Derived/disposable/local (state dir, never the synced vault)."""
    return state_dir() / "knowledge_audit.stamp"


def managed_permissions_manifest() -> Path:
    """The set of settings.json permission strings Precept last wrote (item B). Lets a
    re-sync subtract ONLY Precept's own prior entries, never the user's. Local/derived."""
    return state_dir() / "managed_permissions.json"


def context_rules_path() -> Path:
    """Authored context rules (item A): non-blocking PreToolUse reminders, stored as plain
    JSON the enforce hot path reads directly (stdlib). It is authored CONFIG / source of
    truth (not a derived cache), so it lives in precept_home alongside the other rules."""
    return precept_home() / "context_rules.json"


def event_log() -> Path:
    """Append-only JSONL of one line per guarded tool call (item B-1): {ts, tool, session,
    cwd, file_path, bash_cmd, skill_name}. Derived/disposable telemetry -> the local state
    dir, never the synced vault. `precept report` reads it."""
    return state_dir() / "events.jsonl"


def health_stamp() -> Path:
    """Timestamp of the last system-health (file-staleness) check (item B-3). A once-per-day
    THROTTLE reads/writes this so the reminder can ride SessionStart without nagging.
    Derived/disposable/local (state dir, never the synced vault)."""
    return state_dir() / "health_check.stamp"


def watched_files_config() -> Path:
    """Optional JSON list of file paths the system-health check watches for staleness
    (item B-3). Authored CONFIG (the paths are user-specific and supplied at runtime — the
    repo ships none), so it lives in precept_home. May also come from $PRECEPT_WATCHED_FILES."""
    return precept_home() / "watched_files.json"


def managed_conventions_manifest() -> Path:
    """The set of `.claude/rules/*.md` convention files Precept last wrote (the CONVENTION
    artifact). Lets a re-sync / uninstall delete ONLY files Precept created, never the
    user's own rules files. Local/derived/rebuildable."""
    return state_dir() / "managed_conventions.json"


def decision_log() -> Path:
    """Append-only JSONL of enforcement decisions — one line per policy MATCH (a
    deny/ask/rewrite at PreToolUse, a Stop block, a UserPromptSubmit block or context
    injection): {ts, policy_id, lesson_id, hook_event, decision}. This is what makes
    `fire_count` real: `precept why` and decay governance derive live fire counts from
    it. Derived/disposable/local (state dir, never the synced vault)."""
    return state_dir() / "decisions.jsonl"


def debug_log() -> Path:
    """Opt-in (PRECEPT_DEBUG=1) traceback log for the hook entrypoints, which otherwise
    swallow every exception by design (fail-open). Best-effort: a failed debug write is
    itself swallowed. Derived/disposable/local (state dir, never the synced vault)."""
    return state_dir() / "debug.log"


def stop_surfaced_ledger() -> Path:
    """Per-session record of which JUDGMENT Stop policies have already blocked once, so a
    judgment nudge surfaces ONCE per session and never nags every turn. Keyed by session_id.
    Derived/disposable/local (state dir); safe to delete (worst case, one extra nudge)."""
    return state_dir() / "stop_surfaced.json"


def claude_home() -> Path:
    """The user's real Claude Code config dir — a COMMIT target."""
    return _env_path("PRECEPT_CLAUDE_HOME", Path.home() / ".claude")


def ensure_dirs() -> None:
    for d in (precept_home(), catalog_dir(), notes_dir(), state_dir(), cursors_dir()):
        d.mkdir(parents=True, exist_ok=True)
