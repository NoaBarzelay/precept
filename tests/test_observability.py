"""Observability build: the enforcement DECISION LOG (what makes `fire_count` real),
PRECEPT_DEBUG traceback capture for the fail-open hooks, `precept explain`, and the
metered CAPTURE flow. All hermetic (conftest isolates state dirs; no network)."""

from __future__ import annotations

import io
import json
from datetime import date, timedelta

import pytest

from precept import catalog, enforce, governance, hooks, inference, paths
from precept.evals import tokens as tok
from precept.knowledge import capture as kcapture
from precept.models import GroundedSignals, Lesson, MaybeKnowledge, Origin, Status

# A compiled PreToolUse deny policy, in the exact plain-dict shape the cache holds.
DENY_NPM = {
    "id": "use-pnpm-p1",
    "lesson_id": "use-pnpm",
    "hook_event": "PreToolUse",
    "check_kind": "single_call",
    "decision": "deny",
    "message": "Use pnpm, not npm.",
    "match": {
        "tool": "Bash",
        "conditions": [{"field": "command", "op": "contains", "value": "npm install"}],
    },
}


def _log_lines() -> list[dict]:
    p = paths.decision_log()
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


# --- Task 1: the decision log --------------------------------------------------------

def test_pretooluse_match_appends_decision_record():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install left-pad"}},
        [DENY_NPM],
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    recs = _log_lines()
    assert len(recs) == 1
    r = recs[0]
    assert r["policy_id"] == "use-pnpm-p1"
    assert r["lesson_id"] == "use-pnpm"
    assert r["hook_event"] == "PreToolUse"
    assert r["decision"] == "deny"
    assert r["ts"] > 0


def test_pretooluse_allow_logs_nothing():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}}, [DENY_NPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _log_lines() == []


def test_record_false_skips_the_log():
    # Dry-run callers (eval harness, `precept explain`) must never inflate fire counts.
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install x"}},
        [DENY_NPM], record=False,
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _log_lines() == []


def test_failed_log_write_never_changes_the_decision(monkeypatch):
    def boom():
        raise OSError("disk on fire")
    monkeypatch.setattr(enforce.paths, "decision_log", boom)
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install x"}}, [DENY_NPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"  # fail open held


def test_stop_block_appends_decision_record():
    pol = {
        "id": "tests-first-p1", "lesson_id": "tests-first",
        "hook_event": "Stop", "check_kind": "trajectory",
        "message": "Run the tests before finishing.",
        "trajectory": {"requires": {"tool": "Bash", "conditions": [
            {"field": "command", "op": "contains", "value": "pytest"}]}},
    }
    out = enforce.evaluate_stop_entries(
        [], [pol], verdict_fn=lambda q, c: {"tests-first-p1": {"ok": False, "reason": "claimed done"}},
    )
    assert out.get("decision") == "block"
    recs = _log_lines()
    assert len(recs) == 1
    assert recs[0]["lesson_id"] == "tests-first"
    assert recs[0]["hook_event"] == "Stop"
    assert recs[0]["decision"] == "block"


def test_userpromptsubmit_block_and_context_append_records():
    block_pol = {
        "id": "ticket-p1", "lesson_id": "ticket-required",
        "hook_event": "UserPromptSubmit", "check_kind": "single_call",
        "decision": "deny", "message": "Include the ticket id.",
        "match": {"tool": "UserPromptSubmit", "conditions": [
            {"field": "prompt", "op": "not_contains", "value": "TICKET-"}]},
    }
    out = enforce.evaluate_userpromptsubmit({"prompt": "do the thing"}, [block_pol])
    assert out.get("decision") == "block"
    ctx_pol = {
        "id": "steer-p1", "lesson_id": "steer-env",
        "hook_event": "UserPromptSubmit", "check_kind": "single_call",
        "decision": "context", "message": "Say which env you mean.",
        "match": {"tool": "UserPromptSubmit", "conditions": []},
    }
    enforce.evaluate_userpromptsubmit({"prompt": "TICKET-1 deploy"}, [ctx_pol])
    recs = _log_lines()
    assert [(r["lesson_id"], r["decision"]) for r in recs] == [
        ("ticket-required", "block"), ("steer-env", "context"),
    ]


def test_decision_fire_counts_skips_garbage_lines():
    p = paths.decision_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"lesson_id": "a"}\nnot json\n{"lesson_id": "a"}\n{"nope": 1}\n')
    assert enforce.decision_fire_counts() == {"a": 2}
    assert enforce.decision_fire_counts(p.parent / "missing.jsonl") == {}


def _lesson(rid: str, *, created: date, fire_count: int = 0) -> Lesson:
    return Lesson(
        id=rid, created=created, origin=Origin.CORRECTION, source_session="s",
        status=Status.ACTIVE, trigger=f"{rid} trigger", what_was_wrong="x",
        what_to_do_instead=f"do {rid}", signals=GroundedSignals(fire_count=fire_count),
    )


def test_decay_does_not_retire_a_lesson_that_fires_per_the_log():
    today = date(2026, 7, 1)
    old = today - timedelta(days=60)
    fires_daily = _lesson("fires-daily", created=old)     # static field still 0...
    truly_dead = _lesson("truly-dead", created=old)
    # ...but the decision log shows real enforcement matches.
    enforce._log_decision(
        {"id": "fires-daily-p1", "lesson_id": "fires-daily"}, "PreToolUse", "deny"
    )
    props = governance.propose_decay([fires_daily, truly_dead], threshold_days=30, today=today)
    assert {p.lesson_id for p in props} == {"truly-dead"}


def test_decay_still_respects_the_static_field_for_back_compat():
    today = date(2026, 7, 1)
    old = today - timedelta(days=60)
    legacy = _lesson("legacy-fired", created=old, fire_count=2)  # no log entries at all
    props = governance.propose_decay([legacy], threshold_days=30, today=today)
    assert props == []


def test_why_reflects_the_derived_fire_count():
    from typer.testing import CliRunner

    from precept.cli import app

    catalog.write(_lesson("use-pnpm", created=date(2026, 6, 1)))
    for _ in range(3):
        enforce._log_decision(DENY_NPM, "PreToolUse", "deny")
    res = CliRunner().invoke(app, ["why", "use-pnpm"])
    assert res.exit_code == 0
    assert "fired=3" in res.output


# --- Task 2a: PRECEPT_DEBUG ----------------------------------------------------------

def test_hooks_swallow_errors_silently_by_default(monkeypatch):
    monkeypatch.delenv("PRECEPT_DEBUG", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    def boom(event):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(hooks.enforce, "evaluate_userpromptsubmit", boom)
    assert hooks.userpromptsubmit_main() == 0
    assert not paths.debug_log().exists()


def test_precept_debug_writes_the_traceback_and_stays_fail_open(monkeypatch):
    monkeypatch.setenv("PRECEPT_DEBUG", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    def boom(event):
        raise RuntimeError("kaboom-traceback")
    monkeypatch.setattr(hooks.enforce, "evaluate_userpromptsubmit", boom)
    assert hooks.userpromptsubmit_main() == 0  # still exits 0 (fail open)
    text = paths.debug_log().read_text()
    assert "userpromptsubmit" in text
    assert "RuntimeError: kaboom-traceback" in text
    assert "Traceback" in text


def test_precept_debug_failed_write_still_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("PRECEPT_DEBUG", "1")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a dir")
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(blocker / "nope"))  # mkdir will fail
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    def boom(event):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(hooks.enforce, "evaluate_userpromptsubmit", boom)
    assert hooks.userpromptsubmit_main() == 0


# --- Task 2b: `precept explain` ------------------------------------------------------

@pytest.fixture
def cli():
    from typer.testing import CliRunner

    from precept.cli import app

    return CliRunner(), app


def _write_cache(policies: list[dict]) -> None:
    p = paths.policies_cache()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(policies))


def test_explain_shows_the_match_and_final_deny(cli):
    runner, app = cli
    _write_cache([DENY_NPM])
    res = runner.invoke(app, [
        "explain", "--tool", "Bash", "--input", '{"command": "npm install left-pad"}',
    ])
    assert res.exit_code == 0
    assert "MATCHED" in res.output
    assert "deny" in res.output
    # A dry-run must not touch the decision log.
    assert _log_lines() == []


def test_explain_shows_no_match_and_final_allow(cli):
    runner, app = cli
    _write_cache([DENY_NPM])
    res = runner.invoke(app, ["explain", "--tool", "Bash", "--input", '{"command": "ls"}'])
    assert res.exit_code == 0
    assert "no match" in res.output
    assert "allow" in res.output


def test_explain_flags_out_of_scope_policies(cli):
    runner, app = cli
    repo_pol = {**DENY_NPM, "scope": "repo", "scope_value": "/some/other/repo"}
    _write_cache([repo_pol])
    res = runner.invoke(app, [
        "explain", "--tool", "Bash", "--input", '{"command": "npm install x"}',
        "--cwd", "/tmp",
    ])
    assert res.exit_code == 0
    assert "out of scope" in res.output


def test_explain_stop_reports_unmet_trajectory_gate(cli, tmp_path):
    runner, app = cli
    _write_cache([{
        "id": "tests-first-p1", "lesson_id": "tests-first",
        "hook_event": "Stop", "check_kind": "trajectory",
        "message": "Run the tests before finishing.",
        "trajectory": {"requires": {"tool": "Bash", "conditions": [
            {"field": "command", "op": "contains", "value": "pytest"}]}},
    }])
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")  # no tool calls -> the requirement is unmet
    res = runner.invoke(app, ["explain", "--event", "stop", "--transcript", str(transcript)])
    assert res.exit_code == 0
    assert "UNMET" in res.output
    assert "allow" in res.output  # deterministic dry-run: no AI verdict -> fail open
    assert _log_lines() == []


def test_explain_requires_tool_for_pretooluse(cli):
    runner, app = cli
    _write_cache([DENY_NPM])
    assert runner.invoke(app, ["explain"]).exit_code == 1
    assert runner.invoke(app, ["explain", "--event", "stop"]).exit_code == 1  # no transcript
    assert runner.invoke(app, ["explain", "--event", "bogus"]).exit_code == 1


# --- Task 3: the CAPTURE flow is metered ---------------------------------------------

class _Usage:
    input_tokens = 900
    output_tokens = 120
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeCaptureClient:
    """Anthropic-client stand-in whose parse response carries BOTH parsed_output and
    usage, so meter.record has something real to meter."""

    def __init__(self, maybe: MaybeKnowledge):
        class _messages:
            @staticmethod
            def parse(**kwargs):
                class R:
                    parsed_output = maybe
                    usage = _Usage()
                return R()

        self.messages = _messages()


def test_capture_classify_records_to_the_meter():
    maybe = MaybeKnowledge(chain_of_thought="nothing durable", is_knowledge=False)
    out = kcapture.classify("Recent USER turns:\n\nhello", _FakeCaptureClient(maybe))
    assert out.is_knowledge is False
    rows = tok.load_meter()
    assert len(rows) == 1
    assert rows[0]["flow"] == "capture"
    assert rows[0]["model"] == kcapture.CAPTURE_MODEL
    assert rows[0]["input_tokens"] == 900


def test_capture_classify_failure_notes_inference_health():
    class _Exploding:
        class messages:  # noqa: N801
            @staticmethod
            def parse(**kwargs):
                raise RuntimeError("model down")

    out = kcapture.classify("ctx", _Exploding())
    assert out.is_knowledge is False  # still fails closed (abstains)
    fails = inference.last_failures()
    assert "capture" in fails
    assert fails["capture"]["error_type"] == "RuntimeError"


def test_capture_flow_is_in_the_static_ledger():
    rows = tok.static_ledger(client=None)
    assert any(r["flow"] == "capture" for r in rows)
