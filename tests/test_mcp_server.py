"""MCP server tools, tested as plain functions against a temp catalog (no SDK needed).

The four tools are thin wrappers over the CLI's own internal functions; the SDK wiring
is exercised in one test guarded by importorskip so the suite stays green without the
optional `mcp` extra installed.
"""

from datetime import date

import pytest

from precept import catalog, mcp_server
from precept.models import Determinism, Lesson, Origin, Status


def _seed(lesson_id: str, status: Status = Status.PENDING) -> Lesson:
    # STYLISTIC so keep_lesson never reaches the model-backed synthesis path (offline).
    le = Lesson(
        id=lesson_id,
        created=date(2026, 6, 30),
        origin=Origin.CORRECTION,
        source_session="sess-1",
        status=status,
        determinism=Determinism.STYLISTIC,
        trigger=f"{lesson_id}: installing deps",
        what_was_wrong=f"{lesson_id} was wrong",
        what_to_do_instead=f"{lesson_id} fix",
    )
    catalog.write(le)
    return le


def test_catalog_search_matches_and_filters():
    _seed("use-pnpm", Status.PENDING)
    _seed("cite-sources", Status.ACTIVE)
    ids = {r["id"] for r in mcp_server.catalog_search("pnpm")}
    assert ids == {"use-pnpm"}
    all_ids = {r["id"] for r in mcp_server.catalog_search("")}
    assert {"use-pnpm", "cite-sources"} <= all_ids
    active = mcp_server.catalog_search("", status="active")
    assert [r["id"] for r in active] == ["cite-sources"]


def test_entity_show_includes_fire_count_and_provenance():
    _seed("use-pnpm")
    out = mcp_server.entity_show("use-pnpm")
    assert out["id"] == "use-pnpm"
    assert out["fire_count"] == 0            # nothing has fired yet
    assert out["source_session"] == "sess-1"  # provenance surfaced
    assert out["what_to_do_instead"] == "use-pnpm fix"
    assert mcp_server.entity_show("nope")["error"]


def test_review_pending_lists_only_pending():
    _seed("pend", Status.PENDING)
    _seed("act", Status.ACTIVE)
    ids = {r["id"] for r in mcp_server.review_pending()}
    assert ids == {"pend"}


def test_review_decide_keep_activates():
    _seed("use-pnpm", Status.PENDING)
    res = mcp_server.review_decide("use-pnpm", "keep")
    assert res["decision"] == "kept"
    assert catalog.read(catalog.card_path("use-pnpm")).status == Status.ACTIVE


def test_review_decide_veto_archives_without_deleting():
    _seed("use-pnpm", Status.PENDING)
    res = mcp_server.review_decide("use-pnpm", "veto")
    assert res["decision"] == "vetoed"
    reloaded = catalog.read(catalog.card_path("use-pnpm"))
    assert reloaded.status == Status.ARCHIVED  # archived, card file still present


def test_review_decide_rejects_bad_decision_and_unknown_id():
    _seed("use-pnpm")
    assert mcp_server.review_decide("use-pnpm", "maybe")["error"]
    assert mcp_server.review_decide("nope", "keep")["error"]


def test_build_server_registers_four_tools():
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    # FastMCP exposes registered tools; assert our four are present by name.
    import asyncio

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"catalog_search", "entity_show", "review_pending", "review_decide"} <= names
