"""Tier-1 eval harness: a deterministic confusion matrix over a committed golden
set of enforcement cases. Zero LLM, zero variance, CI-gateable — this is the
trustworthy headline number ("Precept blocks 100% of the violations it has a rule
for, with 0% false-blocks on compliant calls").

Each golden case is self-contained: it carries the compiled policies, a tool call
(or an inline Stop transcript), and the expected outcome (block/allow). We run the
real enforcement matcher and tally TP/FP/TN/FN.

(Tier-2 — a paired, multi-trial, error-barred LIVE before/after with vs without
enforcement — is scaffolded in `live.py`; it needs real agent runs and is reported
with a confidence interval, never as a single dramatic number.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import enforce

GOLDEN = Path(__file__).parent / "golden_enforcement.json"


@dataclass
class Report:
    tp: int = 0  # violation correctly blocked
    fp: int = 0  # compliant call wrongly blocked (a false block)
    tn: int = 0  # compliant call correctly allowed
    fn: int = 0  # violation missed

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def recall(self) -> float:
        """Share of violations Precept blocks — the '100% on the deterministic subset'."""
        denom = self.tp + self.fn
        return 1.0 if denom == 0 else self.tp / denom

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return 1.0 if denom == 0 else self.tp / denom

    @property
    def false_block_rate(self) -> float:
        """Share of compliant calls wrongly blocked — must be 0 to be trustworthy."""
        denom = self.fp + self.tn
        return 0.0 if denom == 0 else self.fp / denom

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 1.0


def _blocked(case: dict[str, Any]) -> bool:
    pols = case["policies"]
    if case.get("kind") == "stop":
        # Claim/standard verdicts are AI in production; the golden set stays
        # deterministic by INJECTING a fake verdict map per case (zero LLM). Cases
        # whose deterministic gates yield no questions never reach the verdict_fn.
        injected = case.get("injected_verdicts", {})
        vf = (lambda questions, context: injected)
        out = enforce.evaluate_stop_entries(case["transcript"], pols, verdict_fn=vf)
        return out.get("decision") == "block"
    out = enforce.evaluate_pretooluse(case["call"], pols)
    return out["hookSpecificOutput"]["permissionDecision"] in ("deny", "ask")


def run(cases: list[dict[str, Any]]) -> tuple[Report, list[dict[str, Any]]]:
    rep = Report()
    rows: list[dict[str, Any]] = []
    for c in cases:
        blocked = _blocked(c)
        should_block = c["expect"] == "block"
        if should_block and blocked:
            rep.tp += 1
            outcome = "TP"
        elif should_block and not blocked:
            rep.fn += 1
            outcome = "FN (missed!)"
        elif not should_block and blocked:
            rep.fp += 1
            outcome = "FP (false block!)"
        else:
            rep.tn += 1
            outcome = "TN"
        rows.append({"id": c["id"], "expect": c["expect"], "blocked": blocked, "outcome": outcome})
    return rep, rows


def load_golden() -> list[dict[str, Any]]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def run_golden() -> tuple[Report, list[dict[str, Any]]]:
    return run(load_golden())
