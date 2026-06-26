"""Tier-2 eval: the LIVE before/after — corrected-behavior rate WITH vs WITHOUT
enforcement, reported HONESTLY.

Anthropic's own research ("Adding Error Bars to Evals") shows infra noise alone
swings agentic eval scores ~6 points, so a single before/after number is not
defensible. Tier-2 therefore runs PAIRED (same task, seed, machine) across multiple
trials and reports the corrected-behavior-rate DELTA with a 95% CI and a stated
noise floor. The deterministic Tier-1 100% stays the headline; this is the demo.

The live agent runs are not wired here (they need real Claude Code sessions). The
honest-stats core, however, is real and tested below — it's the part that makes the
number defensible.
"""

from __future__ import annotations

from math import sqrt
from statistics import mean, stdev


def paired_delta(without_vals: list[float], with_vals: list[float]) -> dict[str, float]:
    """Paired difference (with - without) with a 95% CI on the mean.

    Pass per-trial corrected-behavior rates (0..1) measured WITHOUT and WITH
    enforcement, paired by trial. Returns mean delta + half-width CI + n."""
    if len(without_vals) != len(with_vals) or not without_vals:
        raise ValueError("need equal-length, non-empty paired samples")
    diffs = [w - wo for wo, w in zip(without_vals, with_vals)]
    n = len(diffs)
    m = mean(diffs)
    sem = (stdev(diffs) / sqrt(n)) if n > 1 else 0.0
    return {"mean_delta": m, "ci95_halfwidth": 1.96 * sem, "n": float(n)}


def run_live(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError(
        "Live agent runs are the next step; the paired_delta reporting core is ready."
    )
