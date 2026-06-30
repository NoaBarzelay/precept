"""KNOWLEDGE notes: capture and recall ("what do I know about X").

Storage follows the local-first split:
  - Markdown notes are the SOURCE OF TRUTH (in the catalog dir, safe to sync).
  - A SQLite FTS5 index (on a LOCAL disk, outside any synced folder) makes recall
    fast. The index is DERIVED and disposable — `reindex()` rebuilds it from the
    markdown at any time (and is the executable test of that invariant).

Keyword-first by deliberate decision: FTS5/BM25 + metadata (tag) filtering handles
a personal note set well; semantic/vector recall (sqlite-vec) is added ONLY if a
Recall@k eval shows keyword search missing things — not "embeddings from day one".
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date as _date
from pathlib import Path

import yaml

from .. import paths
from ..models import Note
from ..safety import atomic_write_text, connect_db

_FM = "---"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:8]) or "note"


def note_path(note_id: str) -> Path:
    return paths.notes_dir() / f"{note_id}.md"


def render(note: Note) -> str:
    front = yaml.safe_dump(note.model_dump(mode="json", exclude={"body"}), sort_keys=False, allow_unicode=True).strip()
    return f"{_FM}\n{front}\n{_FM}\n\n# {note.title}\n\n{note.body}\n"


def parse(text: str) -> Note:
    _, front, body = text.split(_FM, 2)
    data = yaml.safe_load(front)
    data["body"] = re.sub(r"^\s*#\s+.*\n", "", body.strip(), count=1).strip()
    return Note.model_validate(data)


def load_all() -> list[Note]:
    d = paths.notes_dir()
    if not d.exists():
        return []
    out: list[Note] = []
    for p in sorted(d.glob("*.md")):
        try:
            out.append(parse(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


# --- FTS5 index (derived) ---------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = connect_db(paths.index_db())
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes "
        "USING fts5(id UNINDEXED, title, body, tags, created UNINDEXED)"
    )
    return conn


def _index(note: Note, conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM notes WHERE id = ?", (note.id,))
    conn.execute(
        "INSERT INTO notes(id, title, body, tags, created) VALUES (?, ?, ?, ?, ?)",
        (note.id, note.title, note.body, " ".join(note.tags), note.created.isoformat()),
    )


def add(title: str, body: str, *, tags: list[str] | None = None, source: str = "",
        today: _date | None = None) -> Note:
    """Write a note (markdown source of truth) and index it for recall."""
    paths.ensure_dirs()
    note = Note(id=_slug(title), created=today or _date.today(), title=title,
                body=body, tags=tags or [], source=source)
    atomic_write_text(note_path(note.id), render(note))
    conn = _connect()
    try:
        _index(note, conn)
    finally:
        conn.close()
    return note


def _build_match(query: str, tag: str | None) -> str:
    terms = re.findall(r"\w+", query or "")
    q = " ".join(terms)
    if tag:
        q = f"{q} tags:{tag}".strip()
    return q


def search(query: str, *, limit: int = 10, tag: str | None = None) -> list[Note]:
    """Recall notes. Metadata (tag) filter applies first, then BM25 ranking."""
    conn = _connect()
    try:
        if not (query or tag):
            rows = conn.execute(
                "SELECT id, title, body, tags, created FROM notes ORDER BY created DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, body, tags, created FROM notes WHERE notes MATCH ? "
                "ORDER BY bm25(notes) LIMIT ?",
                (_build_match(query, tag), limit),
            ).fetchall()
        return [
            Note(id=r[0], title=r[1], body=r[2], tags=r[3].split() if r[3] else [],
                 created=_date.fromisoformat(r[4]))
            for r in rows
        ]
    finally:
        conn.close()


def reindex() -> int:
    """Rebuild the FTS index from the markdown notes (the source of truth)."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM notes")
        notes = load_all()
        for n in notes:
            _index(n, conn)
        return len(notes)
    finally:
        conn.close()
