"""KNOWLEDGE: capture and recall ("what do I know about X").

ONE knowledge store (slice 2). The old `~/.precept/notes` silo is RETIRED: `note` /
`recall` / `reindex` now read and write the SAME vault-backed knowledge index that the
rest of the pillar (index/audit/retrieval) uses, so there is a single source of truth.

  - Markdown knowledge files in the (private, configurable) vault are the SOURCE OF TRUTH.
  - A SQLite FTS5 index on LOCAL disk (outside the synced vault) makes recall fast. It is
    DERIVED and disposable — `reindex()` rebuilds it from the vault markdown at any time
    (and is the executable test of that invariant).

`add()` files a well-formed knowledge file into the vault (auto-routed to the best folder)
and folds it into the live index; `search()` is vault-index BM25 recall returning Note-shaped
rows for back-compat; `reindex()` is the full rebuild. The vault is resolved at runtime
(PRECEPT_VAULT) — never bundled.

Keyword-first by deliberate decision: FTS5/BM25 + tag filtering handles a personal vault
well; semantic/vector recall (sqlite-vec) is added ONLY if a Recall@k eval shows keyword
search missing things — not "embeddings from day one".
"""

from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path

from ..models import Note
from . import config as kconfig
from . import frontmatter
from . import index as kindex
from . import store

# Re-export the entity-routing knobs so callers (and tests) can reach them via the pillar.
file_knowledge = store.file_knowledge


def _vault_db() -> tuple[Path, Path]:
    return kconfig.resolve_vault(), kconfig.knowledge_index_db()


def note_path(note_id: str) -> Path:
    """The vault path of a note filed by `add` (the default Notes/ inbox). `note_id` is the
    title slug; we resolve it back to the on-disk file by matching the stored stem."""
    vault, _ = _vault_db()
    folder = vault / store.DEFAULT_FOLDER
    if folder.exists():
        for p in folder.glob("*.md"):
            if _slug(p.stem) == note_id:
                return p
    # Fall back to a vault-wide scan (a routed note may live elsewhere).
    for p in kindex.iter_markdown(vault):
        if _slug(p.stem) == note_id:
            return p
    return folder / f"{note_id}.md"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return "-".join(s.split("-")[:8]) or "note"


def parse(text: str) -> Note:
    """Parse a vault knowledge file back into a Note (back-compat with the old notes API).
    Tags come from a `tags: [..]` frontmatter line if present."""
    meta, body = frontmatter.split(text)
    title = frontmatter.title_of(body, fallback="note")
    # strip the leading H1 + the trailing `## Sources` section for the recall body.
    no_h1 = re.sub(r"^\s*#\s+.*\n", "", body.strip(), count=1)
    no_sources = re.split(r"(?m)^\s*##\s+Sources\s*$", no_h1)[0].strip()
    return Note(
        id=_slug(title),
        created=_parse_date(meta.get("updated")),
        title=title,
        body=no_sources,
        tags=_parse_tags(meta.get("tags")),
        source="",
    )


def _parse_date(raw: str | None) -> _date:
    try:
        return _date.fromisoformat(raw) if raw else _date.today()
    except ValueError:
        return _date.today()


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.strip("[]").split(",") if t.strip()]


def load_all() -> list[Note]:
    """Every knowledge file in the vault, as Notes (back-compat)."""
    vault, _ = _vault_db()
    out: list[Note] = []
    for p in kindex.iter_markdown(vault):
        try:
            meta, _body = frontmatter.split(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if meta.get("type") != "knowledge":
            continue
        try:
            out.append(parse(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def add(title: str, body: str, *, tags: list[str] | None = None, source: str = "",
        today: _date | None = None) -> Note:
    """File a knowledge note into the vault (auto-routed) and index it for recall.

    This is the migrated `precept note`: the markdown lands in the vault (one knowledge
    store), not the retired `~/.precept/notes`. Returns a Note view of what was written."""
    sources = [source] if source else None
    store.file_knowledge(
        title, body, tags=tags or None, sources=sources, today=today, pending=False,
    )
    return Note(
        id=_slug(title), created=today or _date.today(), title=title,
        body=body, tags=tags or [], source=source,
    )


def search(query: str, *, limit: int = 10, tag: str | None = None) -> list[Note]:
    """Recall knowledge by keyword (vault-index BM25), optionally filtered by tag.

    Returns Note-shaped rows (back-compat). The empty query lists recent docs; a tag filter
    is applied post-hoc over the parsed files (tags live in frontmatter, not the FTS table)."""
    vault, db = _vault_db()
    notes: list[Note]
    if not query:
        # Empty query: list knowledge docs, most-recently-updated first.
        # Most-recent first; over-fetch when tag-filtering so the post-hoc filter still fills.
        window = None if tag else limit
        notes = sorted(load_all(), key=lambda n: n.created, reverse=True)[:window]
    else:
        hits = kindex.search(db, query, k=limit * 3 if tag else limit)
        notes = []
        for h in hits:
            if h.get("type") != "knowledge":
                continue
            p = vault / h["path"]
            try:
                notes.append(parse(p.read_text(encoding="utf-8")))
            except OSError:
                continue
    if tag:
        notes = [n for n in notes if tag in n.tags]
    return notes[:limit]


def reindex() -> int:
    """Rebuild the FTS index from the vault knowledge markdown (the source of truth)."""
    vault, db = _vault_db()
    return kindex.build(vault, db)
