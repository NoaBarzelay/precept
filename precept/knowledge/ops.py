"""Daily knowledge integrity OPS (slice 2): the scheduled audit, the once-per-day throttle,
and the ANN-watch seam.

`audit_proposals(vault)` re-runs the integrity auditor (`knowledge/audit.py`) and the
unfiled-knowledge scan and returns every finding as a PENDING `Proposal` — propose, never
auto-apply (the renamer's `apply_plan` defaults to dry-run and is NOT called here). The
audit can ride SessionStart cheaply because `should_run_today()` THROTTLES it to once per
calendar day via a timestamp in the local state dir.

ANN watch: when a future `vectors` table (semantic recall, sqlite-vec — not built yet)
crosses ~1M rows, brute-force nearest-neighbor gets slow and we should add an HNSW index.
`ann_watch()` is the guarded seam: it returns a suggestion Proposal when the (currently
non-existent) vectors table exceeds the threshold, and a clean no-op until then.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from .. import paths
from ..safety import atomic_write_text, connect_db
from . import audit as kaudit
from . import config as kconfig
from . import naming_spec as kconv
from . import frontmatter
from . import index as kindex
from . import store

# When brute-force NN scan over the vectors table gets slow enough to warrant an ANN
# (HNSW) graph index. Suggestion-only; vectors isn't built, so this never fires today.
ANN_ROW_THRESHOLD = 1_000_000


@dataclass
class Proposal:
    """One PENDING audit proposal surfaced to the user — never auto-applied. `kind` is the
    finding category; `detail` is human-readable; `apply_hint` is the command to act on it."""

    kind: str
    path: str
    detail: str
    apply_hint: str = ""


# --- once-per-day throttle --------------------------------------------------
def last_run_date() -> _date | None:
    """The calendar date the daily audit last ran, or None if it never has."""
    try:
        raw = paths.knowledge_audit_stamp().read_text(encoding="utf-8").strip()
        return _date.fromisoformat(raw)
    except (OSError, ValueError):
        return None


def should_run_today(today: _date | None = None) -> bool:
    """True at most ONCE per calendar day. Lets the audit ride SessionStart without nagging
    (the first session of the day runs it; the rest skip)."""
    today = today or _date.today()
    last = last_run_date()
    return last is None or last < today


def mark_ran(today: _date | None = None) -> None:
    """Record that the daily audit ran today (atomic write to the local state stamp)."""
    paths.ensure_dirs()
    atomic_write_text(paths.knowledge_audit_stamp(), (today or _date.today()).isoformat() + "\n")


# --- unfiled knowledge (PENDING captured files) -----------------------------
def unfiled_knowledge(vault: Path) -> list[Proposal]:
    """Captured knowledge files still marked PENDING/needs-confirmation (slice-2 capture).
    Surfaced so the user keeps or drops each — never silently treated as final."""
    out: list[Proposal] = []
    for p in kindex.iter_markdown(vault):
        if not store.is_pending(p):
            continue
        rel = p.relative_to(vault).as_posix()
        title = frontmatter.title_of(
            p.read_text(encoding="utf-8", errors="replace"), fallback=p.stem
        )
        out.append(Proposal(
            kind="unfiled_knowledge", path=rel,
            detail=f"captured knowledge pending confirmation: '{title}'",
            apply_hint=f"precept knowledge confirm \"{rel}\"",
        ))
    return out


# --- the daily audit (all findings as proposals) ----------------------------
def audit_proposals(vault: str | Path) -> list[Proposal]:
    """Re-run the integrity auditor + the unfiled-knowledge scan and return EVERY finding
    as a PENDING proposal. Nothing is applied (the renamer stays dry-run by default and is
    not invoked here)."""
    vault = Path(vault)
    spec, _stats = kconv.suggest_from_vault(vault)
    findings = kaudit.audit(vault, spec)
    props: list[Proposal] = []
    for f in findings:
        if f.kind == kaudit.FindingKind.RENAME:
            target = f.proposed_stem or "[AI: translate to English]"
            note = " (COLLISION — needs a human target)" if f.collision else ""
            props.append(Proposal(
                kind="rename", path=f.path,
                detail=f"rename -> '{target}' [{', '.join(r.value for r in f.reasons)}], "
                       f"{f.inbound_link_refs} inbound link(s){note}",
                apply_hint="precept knowledge audit  # review, then apply with the renamer",
            ))
        elif f.kind == kaudit.FindingKind.MISPLACEMENT:
            props.append(Proposal(kind="misplacement", path=f.path, detail=f.detail))
        elif f.kind == kaudit.FindingKind.MISSING_FRONTMATTER:
            props.append(Proposal(
                kind="missing_frontmatter", path=f.path,
                detail=f.detail or "missing `type:` frontmatter",
            ))
        elif f.kind == kaudit.FindingKind.MISSING_SOURCES:
            props.append(Proposal(
                kind="missing_sources", path=f.path,
                detail=f.detail or "knowledge file missing a `## Sources` section",
            ))
    props.extend(unfiled_knowledge(vault))
    # ANN watch rides the same daily pass (guarded; a no-op until vectors is built + large).
    ann = ann_watch()
    if ann is not None:
        props.append(ann)
    return props


# --- ANN watch (guarded seam; vectors not built yet) ------------------------
def _vectors_row_count(db_path: Path) -> int | None:
    """Rows in the future semantic-recall `vectors` table, or None when it doesn't exist
    (the case TODAY — sqlite-vec/embeddings are deliberately deferred). Pure read; never
    creates the table."""
    if not Path(db_path).exists():
        return None
    try:
        conn = connect_db(Path(db_path))
    except sqlite3.Error:
        return None
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual') AND name = 'vectors'"
        ).fetchone()
        if not exists:
            return None
        row = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def ann_watch(db_path: Path | None = None) -> Proposal | None:
    """Guarded ANN-watch. Nearest-neighbor recall over `vectors` is
    brute-force, fine to ~tens of thousands of rows. When the count crosses
    ANN_ROW_THRESHOLD (~1M) — where brute-force scan gets slow — SUGGEST adding an HNSW
    index.

    SEAM: `vectors` is NOT built in this slice (no embedding deps), so `_vectors_row_count`
    returns None and this is a clean no-op. The moment the table exists and grows past the
    threshold, this emits a suggestion Proposal — no code change needed then."""
    db = Path(db_path) if db_path is not None else kconfig.knowledge_index_db()
    n = _vectors_row_count(db)
    if n is None or n <= ANN_ROW_THRESHOLD:
        return None
    return Proposal(
        kind="ann_index", path=str(db),
        detail=f"vectors table has {n:,} rows (> {ANN_ROW_THRESHOLD:,}); brute-force "
               "nearest-neighbor will be slow. Suggest adding an HNSW ANN index.",
        apply_hint="implement an HNSW index over the vectors table",
    )


def run_daily(vault: str | Path, *, force: bool = False, today: _date | None = None) -> list[Proposal] | None:
    """Throttled daily entrypoint. Returns the proposals when it ran (and stamps today), or
    None when throttled (already ran today) unless `force=True`."""
    if not force and not should_run_today(today):
        return None
    props = audit_proposals(vault)
    mark_ran(today)
    return props
