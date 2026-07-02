"""The knowledge index: a derived, rebuildable SQLite store over the vault markdown.

Source of truth is the markdown in the (private) vault; THIS is derived and disposable
(reused convention from `precept.knowledge`). Tables:
  - docs(path PK, title, folder, type, updated, hash, body) — one row per .md file.
  - docs_fts — an FTS5 virtual table over (title, body), BM25-ranked, kept in sync
    with `docs` by triggers so search never goes stale against a rebuild.
  - entities(folder PK, ...) — one row per folder that accumulates docs (a light
    entity rollup; an entity "gets a folder once it accumulates multiple files").
  - links(src, dst) — the [[wikilink]] graph (src/dst are doc STEMS, the link target
    form Obsidian resolves by basename).

Concurrency/safety: opens via `safety.connect_db` (WAL + busy_timeout + synchronous=
NORMAL). A rebuild is done into a TEMP db then atomically `os.replace`d over the live
file, so a reader sees either the old whole index or the new one, never a half-built one.

STDLIB ONLY (sqlite3 + FTS5 are stdlib). A `vectors` table for future semantic recall
(sqlite-vec) is intentionally left as a commented stub — no embedding deps yet.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..safety import connect_db
from . import frontmatter

# Bound the recall-biased OR query: a free-text prompt can be hundreds of words, and OR-ing
# them all (especially common ones) unions almost the whole corpus into the BM25 candidate
# set — an O(vault) CPU spin on a large vault. Keep only the most distinctive few.
_MAX_QUERY_TERMS = 24
# Hard wall-clock ceiling for any single FTS query, enforced via a SQLite progress handler.
# Defense in depth: even a pathological query can never peg the CPU on the per-prompt hot
# path; on abort the caller fails open (injects nothing).
_QUERY_BUDGET_S = 1.5


def _install_query_ceiling(conn: sqlite3.Connection, budget_s: float = _QUERY_BUDGET_S) -> None:
    start = time.monotonic()

    def _abort() -> int:
        return 1 if (time.monotonic() - start) > budget_s else 0

    conn.set_progress_handler(_abort, 20000)  # checked every ~20k VM steps

# Folders exempt from the two-type scheme (mirrors the vault convention doc): the
# system dirs that don't carry knowledge/note frontmatter.
EXEMPT_FOLDERS = ("Claude", "Claude Conversations")

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    path    TEXT PRIMARY KEY,   -- vault-relative posix path, e.g. "Career/VC/Bessemer.md"
    title   TEXT NOT NULL,      -- the H1 / filename stem
    folder  TEXT NOT NULL,      -- vault-relative parent dir ("" for the root)
    type    TEXT,               -- "knowledge" | "note" | NULL (missing frontmatter)
    updated TEXT,               -- the knowledge `updated:` date, ISO, or NULL
    hash    TEXT NOT NULL,      -- sha256 of the raw bytes (change detection)
    body    TEXT NOT NULL       -- frontmatter-stripped markdown body
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, body,
    content='docs', content_rowid='rowid'
);

-- Keep the FTS index in lockstep with docs via triggers (content-table pattern).
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, body) VALUES('delete', old.rowid, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, body) VALUES('delete', old.rowid, old.title, old.body);
    INSERT INTO docs_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;

CREATE TABLE IF NOT EXISTS entities (
    folder    TEXT PRIMARY KEY,  -- vault-relative folder that holds docs
    doc_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS links (
    src TEXT NOT NULL,           -- the linking doc's stem
    dst TEXT NOT NULL            -- the [[target]] stem
);
CREATE INDEX IF NOT EXISTS links_dst ON links(dst);

-- FUTURE (deliberately not built yet — no embedding/vector deps in this slice):
-- semantic recall via sqlite-vec. When a Recall@k eval shows keyword search missing
-- things, load the sqlite-vec extension and create:
--   CREATE VIRTUAL TABLE vectors USING vec0(doc_path TEXT, embedding FLOAT[768]);
-- populated alongside docs in build(); search() would then fuse BM25 + vector scores.
"""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def extract_wikilinks(body: str) -> list[str]:
    """Return the de-duplicated [[target]] stems referenced in a body (alias/anchor
    stripped: `[[Foo|bar]]` and `[[Foo#sec]]` both resolve to the `Foo` stem)."""
    seen: list[str] = []
    for m in _WIKILINK.finditer(body):
        stem = m.group(1).strip()
        if stem and stem not in seen:
            seen.append(stem)
    return seen


def iter_markdown(vault: Path) -> list[Path]:
    """Every .md file under the vault, sorted for deterministic builds. Hidden dirs
    (e.g. `.git`, `.obsidian`, `.trash`) are skipped."""
    out: list[Path] = []
    for p in sorted(vault.rglob("*.md")):
        if any(part.startswith(".") for part in p.relative_to(vault).parts):
            continue
        out.append(p)
    return out


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _index_file(conn: sqlite3.Connection, vault: Path, path: Path) -> str:
    """Index one markdown file into an open connection; return its link stem."""
    raw = path.read_bytes()
    rel = path.relative_to(vault).as_posix()
    folder = path.parent.relative_to(vault).as_posix()
    folder = "" if folder == "." else folder
    text = raw.decode("utf-8", errors="replace")
    meta, body = frontmatter.split(text)
    title = frontmatter.title_of(body, fallback=path.stem)
    conn.execute(
        "INSERT OR REPLACE INTO docs(path, title, folder, type, updated, hash, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rel, title, folder, meta.get("type"), meta.get("updated"), _hash(raw), body),
    )
    stem = path.stem
    for dst in extract_wikilinks(body):
        conn.execute("INSERT INTO links(src, dst) VALUES (?, ?)", (stem, dst))
    return folder


def _rollup_entities(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM entities")
    conn.execute(
        "INSERT INTO entities(folder, doc_count) "
        "SELECT folder, COUNT(*) FROM docs GROUP BY folder"
    )


def build(vault: Path, db_path: Path) -> int:
    """(Re)build the whole index from the vault, atomically.

    Builds into a sibling temp DB then `os.replace`s it over the live file, so a
    concurrent reader always sees a complete index. Fully derived: nothing here is a
    source of truth. Returns the number of indexed docs."""
    vault = Path(vault)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(f".{db_path.name}.build.{os.getpid()}")
    for leftover in (tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")):
        leftover.unlink(missing_ok=True)

    conn = connect_db(tmp)
    try:
        # Bulk build: DELETE journal + one transaction is faster and the temp file is
        # disposable, so the WAL preamble's per-write durability isn't needed here.
        conn.execute("PRAGMA journal_mode=MEMORY")
        _create_schema(conn)
        n = 0
        conn.execute("BEGIN")
        for path in iter_markdown(vault):
            try:
                _index_file(conn, vault, path)
                n += 1
            except OSError:
                continue  # unreadable file (e.g. iCloud-evicted) -> skip, don't fail the build
        _rollup_entities(conn)
        conn.execute("COMMIT")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    # Atomic swap into place; clear any stale wal/shm of the old live DB.
    os.replace(tmp, db_path)
    for side in ("-wal", "-shm"):
        db_path.with_name(db_path.name + side).unlink(missing_ok=True)
    return n


def search(db_path: Path, query: str, k: int = 10, *, match_any: bool = False) -> list[dict[str, Any]]:
    """FTS5 BM25 search over (title, body). Returns up to `k` ranked rows (best first)
    as dicts: path, title, folder, type, updated, snippet, score (-bm25; higher=better).

    `match_any=False` (default) AND-s every query token (precise lookup — what the CLI/audit
    use). `match_any=True` OR-s them (recall-biased — for routing a new file and retrieval
    injection over a free-text prompt, where requiring every word would match nothing)."""
    if not Path(db_path).exists():
        return []
    match = _fts_query(query, match_any=match_any)
    if not match:
        return []
    conn = connect_db(Path(db_path))
    _install_query_ceiling(conn)
    try:
        rows = conn.execute(
            "SELECT d.path, d.title, d.folder, d.type, d.updated, "
            "       snippet(docs_fts, 1, '[', ']', ' … ', 12) AS snippet, "
            "       bm25(docs_fts) AS score "
            "FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid "
            "WHERE docs_fts MATCH ? "
            "ORDER BY score LIMIT ?",
            (match, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # query aborted by the time ceiling (or FTS error) -> fail open
    finally:
        conn.close()
    return [
        {
            "path": r[0], "title": r[1], "folder": r[2], "type": r[3],
            "updated": r[4], "snippet": r[5], "score": -float(r[6]),
        }
        for r in rows
    ]


def _fts_query(query: str, *, match_any: bool = False) -> str:
    """Turn free text into a safe FTS5 MATCH expression: bare word tokens (each quoted so
    FTS5 never parses user text as operators/syntax), joined by an implicit AND (default)
    or an explicit OR (`match_any`, recall-biased for routing/retrieval over a sentence)."""
    terms = re.findall(r"\w+", query or "")
    if not terms:
        return ""
    if match_any:
        # Recall-biased OR query (retrieval injection / routing over a free-text sentence):
        # drop stopwords and 1-2 char tokens and CAP the term count, so ultra-common words
        # don't OR the whole corpus into the BM25 candidate set (the cause of the multi-second
        # CPU spin on a large vault). Dedupe, preserve order, keep the first _MAX_QUERY_TERMS.
        seen: set[str] = set()
        kept: list[str] = []
        for t in terms:
            tl = t.lower()
            if len(tl) <= 2 or tl in _ROUTE_STOPWORDS or tl in seen:
                continue
            seen.add(tl)
            kept.append(t)
            if len(kept) >= _MAX_QUERY_TERMS:
                break
        if not kept:
            return ""
        return " OR ".join(f'"{t}"' for t in kept)
    return " ".join(f'"{t}"' for t in terms)


def inbound_link_count(db_path: Path, stem: str) -> int:
    """How many distinct docs contain a [[stem]] link (the rename blast-radius signal)."""
    if not Path(db_path).exists():
        return 0
    conn = connect_db(Path(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT src) FROM links WHERE dst = ?", (stem,)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


# --- incremental upsert (capture / `precept note`) --------------------------
# `build()` is the full rebuild (the derived-invariant test). For the per-turn
# capture path we also need to fold ONE freshly-written file into the live index
# without rebuilding the whole vault — same content-table pattern, on the live DB.
def upsert_file(db_path: Path, vault: Path, path: Path) -> None:
    """Index (or re-index) a single markdown file into the LIVE index DB, creating the
    schema if the DB doesn't exist yet. Removes any prior row + link rows for the file
    first so a re-capture stays idempotent. Derived/disposable; safe to drop and rebuild."""
    vault = Path(vault)
    db_path = Path(db_path)
    conn = connect_db(db_path)
    try:
        _create_schema(conn)
        rel = path.relative_to(vault).as_posix()
        stem = path.stem
        conn.execute("BEGIN")
        conn.execute("DELETE FROM docs WHERE path = ?", (rel,))
        conn.execute("DELETE FROM links WHERE src = ?", (stem,))
        _index_file(conn, vault, path)
        _rollup_entities(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()


def folder_counts(db_path: Path) -> dict[str, int]:
    """Per-folder doc counts from the entity rollup (used to weight folder routing —
    a folder that already accumulates docs is a stronger candidate)."""
    if not Path(db_path).exists():
        return {}
    conn = connect_db(Path(db_path))
    try:
        rows = conn.execute("SELECT folder, doc_count FROM entities").fetchall()
    finally:
        conn.close()
    return {r[0]: int(r[1]) for r in rows}


# Tiny English stopword set for ROUTING ONLY: routing must key on CONTENT words, not on
# "is"/"the"/"a" (which would match almost any doc and mis-route a novel topic). Not used by
# `search`, which keeps its FTS tokens verbatim. Deliberately small + auditable.
_ROUTE_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or "
    "that the to was were will with this these those over under not but if".split()
)


def _content_terms(text: str) -> str:
    """Drop stopwords and 1-2 char tokens so routing matches on meaningful words."""
    terms = [t for t in re.findall(r"\w+", (text or "").lower())
             if len(t) > 2 and t not in _ROUTE_STOPWORDS]
    return " ".join(terms)


def route_folder(db_path: Path, title: str, body: str, k: int = 8) -> tuple[str | None, float]:
    """AUTO-ROUTE a new knowledge file to the best-matching EXISTING folder by content.

    Matches the title+body CONTENT WORDS (stopwords stripped, so a novel topic isn't routed
    on "is"/"the") against the index and tallies the folders of the top-k hits (BM25-weighted).
    Returns (best_folder, confidence in [0,1]); (None, 0.0) when nothing meaningful matches —
    the caller then treats it as a clearly-novel entity and proposes a NEW folder rather than
    forcing a poor fit."""
    query = _content_terms(f"{title} {body}")
    if not query:
        return None, 0.0
    hits = search(db_path, query, k=k, match_any=True)
    if not hits:
        return None, 0.0
    weights: dict[str, float] = {}
    total = 0.0
    for h in hits:
        folder = h.get("folder") or ""
        w = max(h.get("score", 0.0), 0.0) + 1e-6  # BM25 score (higher=better); keep >0
        weights[folder] = weights.get(folder, 0.0) + w
        total += w
    if not weights or total <= 0:
        return None, 0.0
    best = max(weights, key=lambda f: weights[f])
    return best, round(weights[best] / total, 4)
