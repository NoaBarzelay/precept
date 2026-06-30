"""Token-consumption eval for Precept's LLM flows — the 'review and improve' lens.

Two tiers, mirroring the enforcement-eval split (harness.py = Tier-1 deterministic,
live.py = Tier-2):

  STATIC LEDGER (Tier-1) — the FIXED prompt cost of each flow: its system prompt + the
    structured-output schema the SDK injects. Independent of input; this is the part
    Precept *controls*, and exactly what a bloated prompt regresses. Counted with
    Anthropic's free, deterministic count_tokens endpoint (authoritative), and
    snapshotted to token_baseline.json so a CI test can flag drift — the same shape as
    the committed golden enforcement set. Falls back to an offline ~chars/4 ESTIMATE
    when no API key is reachable (clearly labeled, never passed off as exact).

  LIVE METER (Tier-2) — real per-flow input+output tokens captured at every call site by
    meter.record(), aggregated here into per-flow counts, p50/p95, totals, and USD. This
    is the variable cost over your actual sessions: which flow dominates the bill.

`precept tokens` is the CLI surface (default = live meter; --static = ledger + drift).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .. import meter, paths

# Committed baseline of authoritative overhead counts, for CI drift detection.
BASELINE = Path(__file__).parent / "token_baseline.json"
DRIFT_TOLERANCE = 0.10  # >10% change in a flow's fixed overhead is a regression to review


def _flows() -> list[dict[str, Any]]:
    """The five token-spending flows, each as (flow id, model, system prompt, schema
    model). Imported lazily so this module stays import-light for the CLI."""
    from .. import detect, judge, synthesize
    from ..models import MaybeLesson

    return [
        {"flow": meter.DETECT, "model": detect.CLASSIFIER_MODEL,
         "system": detect.SYSTEM, "schema": MaybeLesson},
        {"flow": meter.COMPILE, "model": synthesize.SYNTH_MODEL,
         "system": synthesize.SYSTEM, "schema": synthesize.PolicyDraft},
        {"flow": meter.JUDGE_VERDICT, "model": judge.JUDGE_MODEL,
         "system": judge.SYSTEM, "schema": judge.Verdict},
        {"flow": meter.JUDGE_CONSOLIDATED, "model": judge.JUDGE_MODEL,
         "system": judge.CONSOLIDATED_SYSTEM, "schema": judge.ConsolidatedVerdict},
        {"flow": meter.JUDGE_CONFLICT, "model": judge.JUDGE_MODEL,
         "system": judge.CONFLICT_SYSTEM, "schema": judge.ConflictVerdict},
    ]


def _schema_tool(schema: Any) -> dict[str, Any]:
    """Render a pydantic output model as the tool shape structured output sends, so
    count_tokens prices the schema overhead the real call actually pays."""
    return {
        "name": schema.__name__,
        "description": (schema.__doc__ or "structured output").strip()[:1024],
        "input_schema": schema.model_json_schema(),
    }


def _offline_estimate(flow: dict[str, Any]) -> int:
    """Keyless fallback: ~chars/4 over system + schema JSON. An ESTIMATE, never sold as
    exact — the live meter and the count_tokens path carry the real numbers."""
    chars = len(flow["system"]) + len(json.dumps(flow["schema"].model_json_schema()))
    return chars // 4


def _count_authoritative(flow: dict[str, Any], client: Any) -> int:
    """Exact fixed overhead = count_tokens(system + schema-as-tool + a 1-char user
    slot). The lone "x" isolates the scaffolding from real input (~1 token of noise)."""
    resp = client.messages.count_tokens(
        model=flow["model"],
        system=flow["system"],
        messages=[{"role": "user", "content": "x"}],
        tools=[_schema_tool(flow["schema"])],
    )
    return int(resp.input_tokens)


def static_ledger(client: Any | None = None) -> list[dict[str, Any]]:
    """Per-flow fixed prompt cost. Uses count_tokens when a client/key is available
    (method='count_tokens'), else the offline estimate (method='estimate'), tracked
    per row so a partial outage degrades gracefully instead of failing the whole table."""
    if client is None:
        try:
            import anthropic

            client = anthropic.Anthropic()
        except Exception:
            client = None

    rows: list[dict[str, Any]] = []
    for f in _flows():
        overhead: int | None = None
        method = "estimate"
        if client is not None:
            try:
                overhead = _count_authoritative(f, client)
                method = "count_tokens"
            except Exception:
                overhead = None
        if overhead is None:
            overhead = _offline_estimate(f)
        price = meter.PRICING.get(f["model"], {}).get("input")
        rows.append({
            "flow": f["flow"],
            "model": f["model"],
            "overhead_tokens": overhead,
            "method": method,
            # input $ for 1,000 calls of just the fixed scaffolding (None if unpriced)
            "usd_per_1k_calls": None if price is None
            else round(overhead * price / 1_000_000 * 1_000, 4),
        })
    return rows


# --- baseline + drift (Tier-1 CI gate) ---------------------------------------

def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_baseline(rows: list[dict[str, Any]]) -> None:
    """Snapshot the authoritative overhead counts. Only call with count_tokens rows —
    persisting an estimate would bake an approximation into the CI gate."""
    snap = {r["flow"]: r["overhead_tokens"] for r in rows if r["method"] == "count_tokens"}
    BASELINE.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def drift(rows: list[dict[str, Any]], tolerance: float = DRIFT_TOLERANCE) -> list[dict[str, Any]]:
    """Flows whose authoritative overhead moved more than `tolerance` from the committed
    baseline. Estimate rows and flows absent from the baseline are skipped (can't
    trustworthily compare). Empty list = no regression."""
    base = load_baseline()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["method"] != "count_tokens" or r["flow"] not in base:
            continue
        was = base[r["flow"]]
        now = r["overhead_tokens"]
        if was and abs(now - was) / was > tolerance:
            out.append({"flow": r["flow"], "baseline": was, "current": now,
                        "delta_pct": round((now - was) / was * 100, 1)})
    return out


# --- live meter aggregation (Tier-2) -----------------------------------------

def load_meter() -> list[dict[str, Any]]:
    path = paths.token_usage_log()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue  # skip a torn/partial trailing line
    return rows


def _pct(sorted_vals: list[int], p: int) -> int:
    if not sorted_vals:
        return 0
    k = max(0, min(len(sorted_vals) - 1, round((p / 100) * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll the raw meter up per flow: call count, total in/out tokens, p50/p95 input
    and output, and total USD. Sorted by spend so the dominant flow surfaces first."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r.get("flow", "?")].append(r)
    out: list[dict[str, Any]] = []
    for flow, rs in by.items():
        ins = sorted(int(r.get("input_tokens", 0) or 0) for r in rs)
        outs = sorted(int(r.get("output_tokens", 0) or 0) for r in rs)
        out.append({
            "flow": flow,
            "calls": len(rs),
            "in_total": sum(ins),
            "out_total": sum(outs),
            "in_p50": _pct(ins, 50),
            "in_p95": _pct(ins, 95),
            "out_p50": _pct(outs, 50),
            "out_p95": _pct(outs, 95),
            "cost_usd": round(sum(float(r.get("cost_usd", 0.0) or 0.0) for r in rs), 6),
        })
    out.sort(key=lambda r: r["cost_usd"], reverse=True)
    return out
