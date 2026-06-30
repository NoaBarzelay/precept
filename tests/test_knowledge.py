"""Notes API tests — now over the VAULT-BACKED knowledge index (slice 2: the
`~/.precept/notes` silo is retired; there is ONE knowledge store).

`note` / `recall` / `reindex` (i.e. `knowledge.add` / `.search` / `.reindex`) write and read
knowledge files in the configured (tmp fixture) vault and the local derived index. Covers:
capture + recall, tag filter, markdown round-trip, and the source-of-truth invariant
(delete the DB, reindex from the vault markdown, recall still works)."""

import pytest


@pytest.fixture
def kdirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))  # local, not synced
    vault = tmp_path / "vault"  # the ONE knowledge store; private + configurable, never bundled
    vault.mkdir()
    monkeypatch.setenv("PRECEPT_VAULT", str(vault))
    from precept import knowledge  # import after env is set

    return knowledge


def test_capture_and_recall(kdirs):
    k = kdirs
    k.add("WW2 Pacific theater", "Midway 1942 was the turning point; carriers mattered more than battleships.", tags=["history"])
    k.add("SQLite WAL", "WAL lets many readers and one writer; use busy_timeout.", tags=["eng"])
    hits = k.search("midway carriers")
    assert hits and hits[0].id == "ww2-pacific-theater"


def test_add_writes_well_formed_knowledge_file(kdirs):
    import os
    from pathlib import Path

    k = kdirs
    k.add("Bessemer Venture Partners", "A venture firm founded in 1911.", tags=["vc"])
    vault = Path(os.environ["PRECEPT_VAULT"])
    files = list(vault.rglob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "type: knowledge" in text       # proper knowledge frontmatter
    assert "updated:" in text
    assert "## Sources" in text            # the auditor's required section
    assert "# Bessemer Venture Partners" in text


def test_tag_filter(kdirs):
    k = kdirs
    k.add("Note A", "shared keyword apple", tags=["x"])
    k.add("Note B", "shared keyword apple", tags=["y"])
    hits = k.search("apple", tag="y")
    assert len(hits) == 1 and hits[0].tags == ["y"]


def test_markdown_roundtrip(kdirs):
    k = kdirs
    n = k.add("Title Here", "Body line one.\nBody line two.", tags=["a", "b"])
    back = k.parse(k.note_path(n.id).read_text())
    assert back.title == "Title Here"
    assert "Body line one." in back.body and "Body line two." in back.body
    assert back.tags == ["a", "b"]


def test_index_is_derived_rebuildable(kdirs):
    k = kdirs
    k.add("Recoverable note", "the body mentions zebra", tags=["z"])
    # nuke the derived index entirely
    from precept.knowledge import config as kconfig
    kconfig.knowledge_index_db().unlink()
    # rebuild purely from the vault markdown, recall still works
    assert k.reindex() == 1
    assert k.search("zebra")[0].title == "Recoverable note"


def test_empty_query_lists_recent(kdirs):
    k = kdirs
    k.add("One", "alpha body")
    k.add("Two", "beta body")
    assert len(k.search("")) == 2
