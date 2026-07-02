"""Token-eval tests. The deterministic parts (pricing, meter round-trip, aggregation,
offline ledger, drift) run with zero network — the static ledger's authoritative path
is exercised with an injected fake count_tokens client, never a live call."""

from __future__ import annotations


import pytest

from precept import meter
from precept.evals import tokens as tok


# --- pricing ----------------------------------------------------------------

def test_cost_usd_prices_input_and_output():
    # Haiku 4.5: $1/MTok in, $5/MTok out -> 1000 in + 200 out = $0.001 + $0.001
    assert meter.cost_usd("claude-haiku-4-5", 1000, 200) == pytest.approx(0.002)


def test_cost_usd_cache_tokens_bill_at_reduced_and_premium_factors():
    # cache read ~0.1x input, cache write ~1.25x input
    c = meter.cost_usd("claude-sonnet-4-6", 0, 0, cache_read_tokens=1_000_000,
                       cache_creation_tokens=1_000_000)
    assert c == pytest.approx(3.0 * 0.1 + 3.0 * 1.25)


def test_cost_usd_unknown_model_is_unpriced_not_guessed():
    assert meter.cost_usd("some-future-model", 10_000, 10_000) == 0.0


# --- meter record round-trip (uses a tmp state dir via env) ------------------

class _FakeUsage:
    input_tokens = 1200
    output_tokens = 300
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeResp:
    usage = _FakeUsage()


def test_record_appends_a_priced_row(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    meter.record(meter.DETECT, "claude-haiku-4-5", _FakeResp(), now=123.0)
    rows = tok.load_meter()
    assert len(rows) == 1
    r = rows[0]
    assert r["flow"] == meter.DETECT and r["input_tokens"] == 1200
    # $1/MTok in, $5/MTok out: 1200*1e-6 + 300*5e-6 = 0.0012 + 0.0015
    assert r["cost_usd"] == pytest.approx(0.0027)


def test_record_is_fail_open_on_missing_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    meter.record(meter.COMPILE, "claude-sonnet-4-6", object())  # no .usage
    assert tok.load_meter() == []  # dropped the row, did not raise


# --- aggregation ------------------------------------------------------------

def test_aggregate_groups_by_flow_and_sorts_by_spend():
    rows = [
        {"flow": "detect", "input_tokens": 100, "output_tokens": 10, "cost_usd": 0.001},
        {"flow": "detect", "input_tokens": 300, "output_tokens": 30, "cost_usd": 0.003},
        {"flow": "compile", "input_tokens": 500, "output_tokens": 50, "cost_usd": 0.010},
    ]
    agg = tok.aggregate(rows)
    assert agg[0]["flow"] == "compile"  # highest spend first
    detect = next(a for a in agg if a["flow"] == "detect")
    assert detect["calls"] == 2 and detect["in_total"] == 400
    assert detect["in_p95"] == 300


# --- static ledger ----------------------------------------------------------

class _FakeCount:
    def __init__(self, n):
        self.input_tokens = n


class _FakeClient:
    """Returns a fixed token count for every flow — exercises the authoritative path
    deterministically without a network call."""
    class messages:  # noqa: N801 — mirrors the SDK's client.messages.count_tokens shape
        @staticmethod
        def count_tokens(**kwargs):
            return _FakeCount(777)


def test_static_ledger_authoritative_with_injected_client():
    rows = tok.static_ledger(client=_FakeClient())
    assert len(rows) == 6  # the six token-spending flows
    assert all(r["method"] == "count_tokens" for r in rows)
    assert all(r["overhead_tokens"] == 777 for r in rows)
    # detect/judge are Haiku ($1/MTok in): 777 tok * 1000 calls -> $0.777
    det = next(r for r in rows if r["flow"] == meter.DETECT)
    assert det["usd_per_1k_calls"] == pytest.approx(0.777)


def test_static_ledger_falls_back_to_offline_estimate_without_client():
    # No client and no key path: still returns a full table, flagged as estimate.
    rows = tok.static_ledger(client=None)
    # In CI there's no key, so expect estimates; each is a positive int.
    assert len(rows) == 6
    for r in rows:
        assert r["overhead_tokens"] > 0
        assert r["method"] in ("count_tokens", "estimate")


def test_drift_flags_only_real_regressions(monkeypatch):
    rows = [
        {"flow": "detect", "overhead_tokens": 100, "method": "count_tokens"},
        {"flow": "compile", "overhead_tokens": 150, "method": "count_tokens"},
        {"flow": "judge.verdict", "overhead_tokens": 999, "method": "estimate"},
    ]
    monkeypatch.setattr(tok, "load_baseline",
                        lambda: {"detect": 100, "compile": 100, "judge.verdict": 100})
    d = tok.drift(rows, tolerance=0.10)
    flows = {x["flow"] for x in d}
    assert "compile" in flows       # 100 -> 150 is +50%, over tolerance
    assert "detect" not in flows    # unchanged
    assert "judge.verdict" not in flows  # estimate rows never compared
