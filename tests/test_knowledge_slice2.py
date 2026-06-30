"""Slice-2 knowledge tests over a TMP fixture vault (never the real, private vault).

Covers: CAPTURE writes a well-formed, routed, PENDING knowledge file; the notes commands
now read/write the vault-backed index (one store); RETRIEVAL injection returns relevant
additionalContext for a planted query; the daily AUDIT surfaces planted findings as
proposals; the once-per-day THROTTLE fires at most once per day; and the guarded ANN-watch
seam is a no-op until the (unbuilt) vectors table is large.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from precept.knowledge import capture as kcapture
from precept.knowledge import config as kconfig
from precept.knowledge import index as kindex
from precept.knowledge import ops as kops
from precept.knowledge import retrieval as kretrieval
from precept.knowledge import store as kstore
from precept.models import ExtractedKnowledge, MaybeKnowledge


def _write(vault: Path, rel: str, body: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp fixture vault + local state dir, wired via env (configurable, never bundled)."""
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("PRECEPT_VAULT", str(vault))
    # A seed knowledge folder so routing has a real existing home to match against.
    _write(vault, "Career/VC/Index Ventures.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Index Ventures\n\n"
           "Index Ventures is a venture capital firm investing in startups.\n\n## Sources\n- y\n")
    db = kconfig.knowledge_index_db()
    kindex.build(vault, db)
    return vault, db


class _FakeClient:
    """Stands in for the Anthropic client: returns a fixed MaybeKnowledge (no network)."""

    def __init__(self, maybe: MaybeKnowledge):
        self._maybe = maybe

        class _messages:
            @staticmethod
            def parse(**kwargs):
                class R:
                    parsed_output = maybe
                return R()

        self.messages = _messages()


# --- capture ----------------------------------------------------------------
def test_capture_writes_routed_pending_knowledge_file(env):
    vault, db = env
    maybe = MaybeKnowledge(
        chain_of_thought="user stated a durable fact about a VC firm",
        is_knowledge=True,
        knowledge=ExtractedKnowledge(
            title="Bessemer Venture Partners",
            body="Bessemer Venture Partners is a venture capital firm founded in 1911.",
            tags=["vc"], sources=["https://example.com/bessemer"],
        ),
    )
    turns = ["fyi Bessemer Venture Partners is a venture capital firm founded in 1911"]
    res = kcapture.capture_from_turns(turns, client=_FakeClient(maybe))

    assert res is not None
    p = vault / res.rel
    assert p.exists()
    text = p.read_text()
    # Well-formed knowledge file: frontmatter type/updated, pending marker, Sources section.
    assert "type: knowledge" in text
    assert "updated:" in text
    assert "precept_status: pending" in text
    assert "## Sources" in text
    assert "https://example.com/bessemer" in text
    # AUTO-ROUTED to the existing VC folder (content match), not the default inbox.
    assert res.folder == "Career/VC"
    assert res.routed is True
    assert kstore.is_pending(p) is True


def test_capture_routes_novel_topic_to_new_folder(env):
    vault, db = env
    maybe = MaybeKnowledge(
        chain_of_thought="durable but unrelated to existing folders",
        is_knowledge=True,
        knowledge=ExtractedKnowledge(
            title="Sourdough Hydration",
            body="Sourdough hydration is the ratio of water to flour by weight.",
            tags=["baking"], sources=[],
        ),
    )
    res = kcapture.capture_from_turns(["note that sourdough hydration is water over flour"],
                                      client=_FakeClient(maybe))
    assert res is not None
    # Nothing in the vault is about baking -> NOT forced into Career/VC; lands in the default.
    assert res.folder == kstore.DEFAULT_FOLDER
    assert res.routed is False


def test_capture_abstains_without_filing(env):
    vault, db = env
    maybe = MaybeKnowledge(chain_of_thought="just a task", is_knowledge=False,
                           abstain_reason="no durable knowledge")
    before = set(vault.rglob("*.md"))
    res = kcapture.capture_from_turns(["fyi please run the tests"], client=_FakeClient(maybe))
    assert res is None
    assert set(vault.rglob("*.md")) == before  # nothing written


def test_capture_prefilter_skips_irrelevant_turns(env):
    # No cue words -> no LLM call at all (client.parse would raise if reached).
    class _Boom:
        class messages:
            @staticmethod
            def parse(**kwargs):
                raise AssertionError("should not classify a clearly-irrelevant turn")

    assert kcapture.capture_from_turns(["ok thanks"], client=_Boom()) is None


def test_capture_noop_without_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("PRECEPT_VAULT", raising=False)
    maybe = MaybeKnowledge(chain_of_thought="x", is_knowledge=True,
                           knowledge=ExtractedKnowledge(title="T", body="b"))
    # No vault configured -> fail-open no-op (never guesses a path).
    assert kcapture.capture_from_turns(["the company is based in NYC"],
                                       client=_FakeClient(maybe)) is None


# --- one knowledge store: notes commands hit the vault index ----------------
def test_notes_commands_use_vault_backed_index(env):
    vault, db = env
    from precept import knowledge

    knowledge.add("Tower Research Capital", "Tower is a quantitative trading firm.", tags=["quant"])
    # The note is a vault knowledge file (one store), and the SAME index now finds it.
    hits = kindex.search(db, "quantitative trading", k=5)
    assert any(h["title"] == "Tower Research Capital" for h in hits)
    # And the notes recall API returns it too.
    recall = knowledge.search("quantitative trading")
    assert recall and recall[0].title == "Tower Research Capital"


def test_capture_confirm_promotes_to_final(env):
    vault, db = env
    res = kstore.file_knowledge("Pending Topic", "Some durable fact.", pending=True)
    p = vault / res.rel
    assert kstore.is_pending(p) is True
    kstore.confirm(p)
    assert kstore.is_pending(p) is False
    assert "precept_status" not in p.read_text()


# --- retrieval injection ----------------------------------------------------
def test_retrieval_returns_relevant_context(env):
    vault, db = env
    ctx = kretrieval.retrieval_context("which firm invests in startups in venture capital")
    assert ctx is not None
    assert "Index Ventures" in ctx
    # Bounded: bodies are truncated and the block is capped.
    assert len(ctx) <= 2000


def test_retrieval_empty_query_or_no_match(env):
    assert kretrieval.retrieval_context("") is None
    assert kretrieval.retrieval_context("zzzznomatchtoken qqqqx") is None


def test_userpromptsubmit_injects_retrieval(env):
    from precept import enforce

    out = enforce.evaluate_userpromptsubmit(
        {"prompt": "tell me about the venture capital firm Index Ventures"}, []
    )
    # Not blocking, but injects additionalContext (slice 2 retrieval).
    assert "hookSpecificOutput" in out
    assert "Index Ventures" in out["hookSpecificOutput"]["additionalContext"]


def test_userpromptsubmit_no_injection_when_nothing_relevant(env):
    from precept import enforce

    assert enforce.evaluate_userpromptsubmit({"prompt": "zzzznomatch qqqq"}, []) == {}


# --- daily audit + proposals ------------------------------------------------
def test_audit_surfaces_planted_findings_as_proposals(env):
    vault, db = env
    # Plant: an underscored+dated filename (rename), a missing-frontmatter file, a
    # knowledge file with no Sources, and a PENDING captured file (unfiled).
    _write(vault, "Career/VC/old_fund_2026-05-01.md",
           "---\ntype: knowledge\nupdated: 2026-05-01\n---\n# old fund\n\nbody\n\n## Sources\n- z\n")
    _write(vault, "Career/No Type Here.md", "# No Type Here\n\nno frontmatter\n")
    _write(vault, "Career/No Sources Here.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# No Sources Here\n\nbody only\n")
    kstore.file_knowledge("Captured Pending Item", "A pending captured fact.", pending=True)

    props = kops.audit_proposals(vault)
    kinds = {p.kind for p in props}
    assert "rename" in kinds
    assert "missing_frontmatter" in kinds
    assert "missing_sources" in kinds
    assert "unfiled_knowledge" in kinds
    # Proposals are PENDING — nothing was renamed/changed on disk.
    assert (vault / "Career/VC/old_fund_2026-05-01.md").exists()


def test_daily_throttle_fires_at_most_once_per_day(env):
    vault, db = env
    today = date(2026, 6, 30)
    first = kops.run_daily(vault, today=today)
    assert first is not None              # ran
    assert kops.should_run_today(today) is False
    second = kops.run_daily(vault, today=today)
    assert second is None                 # throttled — same day
    # A new day re-enables it.
    tomorrow = today + timedelta(days=1)
    assert kops.should_run_today(tomorrow) is True
    assert kops.run_daily(vault, today=tomorrow) is not None


def test_daily_force_overrides_throttle(env):
    vault, db = env
    today = date(2026, 6, 30)
    assert kops.run_daily(vault, today=today) is not None
    assert kops.run_daily(vault, today=today) is None
    assert kops.run_daily(vault, force=True, today=today) is not None


# --- ANN watch seam ---------------------------------------------------------
def test_ann_watch_is_noop_without_vectors_table(env):
    vault, db = env
    # vectors is intentionally not built in this slice -> clean no-op.
    assert kops.ann_watch(db) is None


def test_ann_watch_suggests_when_vectors_table_exceeds_threshold(env, monkeypatch):
    vault, db = env
    # Simulate a large future vectors table cheaply by lowering the threshold and creating
    # a tiny vectors table with a couple rows (the seam triggers on count > threshold).
    monkeypatch.setattr(kops, "ANN_ROW_THRESHOLD", 1)
    from precept.safety import connect_db

    conn = connect_db(db)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS vectors (id INTEGER)")
        conn.execute("INSERT INTO vectors(id) VALUES (1),(2),(3)")
    finally:
        conn.close()
    prop = kops.ann_watch(db)
    assert prop is not None and prop.kind == "ann_index"
    assert "HNSW" in prop.detail
