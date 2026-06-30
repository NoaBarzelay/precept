"""Item 6 — rule governance: decay/supersede/conflict proposals are produced (never
auto-applied), applying them archives (never hard-deletes), and an ARCHIVED rule is
excluded from the enforcement cache."""

import json

from datetime import date, timedelta

from precept import catalog, compile as _compile, governance, paths
from precept.models import (
    CheckKind, Decision, EnforcementTier, GroundedSignals, HookEvent, Lesson,
    Origin, Policy, Status,
)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(tmp_path / "claude"))


def _rule(rid, *, status=Status.ACTIVE, created=None, fire_count=0, policy=False) -> Lesson:
    le = Lesson(
        id=rid, created=created or date(2026, 6, 30), origin=Origin.CORRECTION,
        source_session="s", status=status, trigger=f"{rid} trigger",
        what_was_wrong="did X", what_to_do_instead=f"do {rid}",
        signals=GroundedSignals(fire_count=fire_count),
    )
    if policy:
        le.policies = [Policy(
            id=f"{rid}-p1", lesson_id=rid, enforcement_tier=EnforcementTier.HARD,
            hook_event=HookEvent.STOP, check_kind=CheckKind.JUDGMENT, decision=Decision.DENY,
            message="m", judgment_prompt="is it ok?",
        )]
    return le


# --- decay ------------------------------------------------------------------
def test_decay_proposes_old_never_fired_active_rules():
    today = date(2026, 6, 30)
    old = _rule("old", created=today - timedelta(days=40), fire_count=0)
    fired = _rule("fired", created=today - timedelta(days=40), fire_count=3)
    young = _rule("young", created=today - timedelta(days=5), fire_count=0)
    pending = _rule("pend", created=today - timedelta(days=40), status=Status.PENDING)
    props = governance.propose_decay(
        [old, fired, young, pending], threshold_days=30, today=today
    )
    ids = {p.lesson_id for p in props}
    assert ids == {"old"}  # fired (active), young (recent), pending (never enforced) excluded


def test_apply_decay_archives_and_excludes_from_cache(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    le = _rule("dead", created=date(2026, 1, 1), fire_count=0, policy=True)
    catalog.write(le)
    # Active rule compiles into the cache...
    _compile.compile_all()
    assert any(p["lesson_id"] == "dead" for p in json.loads(paths.policies_cache().read_text()))
    # ...decaying it archives it (recoverable, not removed) and drops it from the cache.
    archived = governance.apply_decay("dead")
    assert archived.status == Status.ARCHIVED
    assert catalog.card_path("dead").exists()  # NOT hard-deleted
    _compile.compile_all()
    assert not any(p["lesson_id"] == "dead" for p in json.loads(paths.policies_cache().read_text()))


# --- supersede --------------------------------------------------------------
def test_supersede_archives_old_with_pointer(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    catalog.write(_rule("v1"))
    catalog.write(_rule("v2"))
    old, new = governance.apply_supersede("v1", "v2")
    assert old.status == Status.ARCHIVED
    assert old.superseded_by == "v2"
    assert new.supersedes == "v1"
    # persisted to the cards
    reloaded = {x.id: x for x in catalog.load_all()}
    assert reloaded["v1"].superseded_by == "v2"
    assert reloaded["v2"].supersedes == "v1"


def test_supersede_rejects_self():
    import pytest

    with pytest.raises(ValueError):
        governance.apply_supersede("a", "a")


# --- conflict detection (LLM-judge seam, injectable) ------------------------
def test_conflict_detection_uses_injected_verdict_fn():
    a = _rule("use-npm")
    a.what_to_do_instead = "always use npm"
    b = _rule("use-pnpm")
    b.what_to_do_instead = "never use npm, use pnpm"
    c = _rule("cite")
    c.what_to_do_instead = "cite your sources"

    seen = []

    def vf(text_a, text_b):
        seen.append((text_a, text_b))
        # only the npm-vs-pnpm pair conflicts
        if "npm" in text_a and "pnpm" in text_b or "pnpm" in text_a and "npm" in text_b:
            return {"conflicts": True, "reason": "npm vs pnpm"}
        return {"conflicts": False, "reason": ""}

    props = governance.detect_conflicts([a, b, c], verdict_fn=vf)
    assert len(props) == 1
    assert {props[0].lesson_a, props[0].lesson_b} == {"use-npm", "use-pnpm"}
    assert props[0].reason == "npm vs pnpm"
    assert len(seen) == 3  # 3 active rules -> 3 pairs compared


def test_conflict_detection_fails_open_on_none():
    a, b = _rule("a"), _rule("b")
    # a None verdict (model hiccup) must NOT propose a conflict
    assert governance.detect_conflicts([a, b], verdict_fn=lambda x, y: None) == []


def test_conflict_detection_only_compares_active_rules():
    a = _rule("a")
    b = _rule("b", status=Status.ARCHIVED)
    called = []
    governance.detect_conflicts([a, b], verdict_fn=lambda x, y: called.append(1) or {"conflicts": False})
    assert called == []  # only one active rule -> no pair to compare
