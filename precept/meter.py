"""Token metering — capture each LLM flow's real usage and price it.

Every Precept LLM flow (DETECT, COMPILE, the three JUDGE verdicts) calls
`client.messages.parse(...)` and today keeps only `.parsed_output`, discarding the
`.usage` that rides on the same response. `meter.record(flow, model, resp)` pulls
that usage off and appends ONE row to a local JSONL meter, so `precept tokens`
(see evals/tokens.py) can show which flow actually spends the tokens.

Two non-negotiables:
  - FAIL-OPEN. A metering error must never disturb the flow it measures — the whole
    body is wrapped, and any failure just drops the row. Observability is never worth
    breaking enforcement or detection over.
  - LOCAL/DERIVED. The meter lives in paths.state_dir() (rebuildable, disposable),
    never the synced vault — same rule as the policy cache and SQLite index.

Billing reality: Precept runs on a Claude Code SUBSCRIPTION (OAuth), not metered API
keys. So the native unit here is TOKENS — they draw down the subscription's usage
quota / rate limits. The USD figure is NOTIONAL: what the same tokens WOULD cost at
published per-token API rates. Treat it as a weight/relative-cost proxy for comparing
flows, not a bill. Tokens lead every readout; dollars are the secondary lens (and the
real number if you ever point a flow at a metered API key). Rates are the single source
of truth here (model catalog, claude-api skill, 2026-06); cache reads ~0.1x input,
cache writes ~1.25x input.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import paths

# Flow identifiers — the five token-spending call sites. Imported by the call sites
# (so the string is defined once) and by evals/tokens.py (the static-ledger registry).
DETECT = "detect"
COMPILE = "compile"
JUDGE_VERDICT = "judge.verdict"
JUDGE_CONSOLIDATED = "judge.consolidated"
JUDGE_CONFLICT = "judge.conflict"

# NOTIONAL USD per 1,000,000 tokens (input, output) at published API rates — a weight
# proxy, NOT a bill (Precept bills via the Claude Code subscription). Source: model catalog.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},  # kept for pricing old meter records
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
}

_CACHE_READ_FACTOR = 0.1  # cache reads bill ~0.1x the input rate
_CACHE_WRITE_FACTOR = 1.25  # cache writes (5m TTL) bill ~1.25x the input rate


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Notional cost of one call (USD at published API rates — a weight proxy, not a
    subscription bill). Returns 0.0 for an unpriced model (flagged by callers, not
    guessed) so a new model can't silently inflate a bogus figure. Note
    `input_tokens` from the SDK is the UNCACHED remainder — cache read/creation are
    separate buckets, billed at their own factors."""
    p = PRICING.get(model)
    if p is None:
        return 0.0
    inp = p["input"] / 1_000_000
    out = p["output"] / 1_000_000
    return (
        input_tokens * inp
        + output_tokens * out
        + cache_read_tokens * inp * _CACHE_READ_FACTOR
        + cache_creation_tokens * inp * _CACHE_WRITE_FACTOR
    )


def usage_dict(resp: Any) -> dict[str, int] | None:
    """Pull the four token counts off a response's `.usage`. None if absent (e.g. an
    injected fake client in tests, or a non-message response) — caller drops the row."""
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


def record(flow: str, model: str, resp: Any, *, now: float | None = None) -> None:
    """Append one usage row for `flow` to the local JSONL meter. Best-effort and
    FAIL-OPEN: any error (no usage, unwritable dir, serialization) is swallowed — a
    metering hiccup must never propagate into the flow being measured.

    The meter is append-only JSONL (one self-contained row per call), so a torn write
    costs at most the trailing line; aggregation skips unparseable lines."""
    try:
        u = usage_dict(resp)
        if u is None:
            return
        row = {
            "ts": now if now is not None else time.time(),
            "flow": flow,
            "model": model,
            **u,
            "cost_usd": round(
                cost_usd(
                    model,
                    u["input_tokens"],
                    u["output_tokens"],
                    u["cache_read_input_tokens"],
                    u["cache_creation_input_tokens"],
                ),
                6,
            ),
        }
        path = paths.token_usage_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        return  # fail-open: metering must never disturb the flow it measures
