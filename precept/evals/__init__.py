"""The eval harness — Precept's #1 hiring signal. NOT YET IMPLEMENTED.

Locked two-tier design:
  TIER 1 (the trustworthy headline): a deterministic confusion matrix over a
    committed seed set of (correction, fresh-task) pairs. Zero variance, CI-gated.
    Reported per-class precision/recall (esp. false-mint rate) + Cohen's kappa vs
    the human keep/veto decisions. This is the "~100% on the deterministic subset".
  TIER 2 (the demo): a small headless with-vs-without-enforcement run, PAIRED and
    multi-trial, reported as a corrected-behavior-rate delta with a 95% CI and an
    explicit infra-noise floor (single-run before/after numbers are unreliable).

Metric = corrected-behavior / agent-recovery rate, NOT block-rate. Seed tasks are
sourced from real Stop-hook transcript failures (error-analysis first).
"""
