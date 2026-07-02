"""ReDoS protection for model-authored regex.

Precept's single_call matchers carry regex patterns authored by a model at COMPILE
time from a correction. Python's `re` has no timeout and is vulnerable to catastrophic
backtracking, so a valid but pathological pattern (for example `(a+)+$`) run against a
long input can hang the enforcement hook and stall a session. This is the same threat
class as the fork bomb: model-authored logic must never be able to harm the machine.

Two layers:
- `looks_catastrophic` rejects the obvious nested-quantifier forms at COMPILE so they
  never enter the catalog.
- `safe_search` runs the match under a wall-clock bound at ENFORCE so any remaining
  pathological pattern fails safe (returns None, treated as no match) instead of hanging.
"""

from __future__ import annotations

import re
import threading

REGEX_TIMEOUT_S = 1.0
MAX_PATTERN = 2000

# A quantified group whose body is itself unboundedly quantified, e.g. (a+)+, (a*)*,
# (a+)*, (.*)+ , is the classic catastrophic-backtracking construct. Deliberately narrow
# so legitimate patterns are not rejected; the runtime bound in `safe_search` is the
# complete backstop.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*]")


def looks_catastrophic(pattern: str) -> bool:
    """Conservative heuristic for the obvious ReDoS constructs, used at COMPILE to
    refuse a pattern before it enters the catalog."""
    if len(pattern) > MAX_PATTERN:
        return True
    return _NESTED_QUANTIFIER.search(pattern) is not None


def safe_search(pattern: str, text: str, timeout: float = REGEX_TIMEOUT_S) -> bool | None:
    """`re.search` under a wall-clock bound. Returns True or False for a decided match,
    or None if the pattern errored or exceeded `timeout`. The caller treats None as
    fail-safe: no match, never block. The worker is a daemon thread, so a truly hung
    match is abandoned rather than allowed to block the hook or the process."""
    out: list[bool] = []

    def _run() -> None:
        try:
            out.append(re.search(pattern, text) is not None)
        except re.error:
            pass  # invalid pattern -> leave `out` empty -> None (fail-safe)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return out[0] if out else None
