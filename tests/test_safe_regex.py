"""ReDoS protection: model-authored regex must never hang the enforcement hook.

Two layers are tested: `looks_catastrophic` + the Condition validator reject the obvious
catastrophic patterns at COMPILE, and `safe_search` bounds any that slip through at
ENFORCE. The timeout mechanism is exercised with a monkeypatched slow match rather than a
real exponential regex, so the suite never leaves a hot thread spinning.
"""

import time

import pytest

from precept import enforce, safe_regex
from precept.models import Condition, MatchOp


def test_looks_catastrophic_flags_nested_quantifiers_and_overlong():
    assert safe_regex.looks_catastrophic(r"(a+)+$")
    assert safe_regex.looks_catastrophic(r"(.*)*")
    assert safe_regex.looks_catastrophic(r"(a+)*b")
    assert safe_regex.looks_catastrophic("a" * (safe_regex.MAX_PATTERN + 1))
    # legitimate patterns are not rejected
    assert not safe_regex.looks_catastrophic(r"\bnpm\b")
    assert not safe_regex.looks_catastrophic(r"[A-Z]+-[0-9]+")


def test_condition_rejects_catastrophic_regex_at_construction():
    with pytest.raises(ValueError):
        Condition(field="command", op=MatchOp.REGEX, value=r"(a+)+$")
    with pytest.raises(ValueError):
        Condition(field="command", op=MatchOp.NOT_REGEX, value=r"(.*)*")
    # a normal regex condition still constructs fine
    Condition(field="command", op=MatchOp.REGEX, value=r"\bnpm\b")
    # non-regex ops are never rejected by this check
    Condition(field="command", op=MatchOp.CONTAINS, value=r"(a+)+$")


def test_safe_search_normal_and_invalid_patterns():
    assert safe_regex.safe_search(r"\bnpm\b", "run npm install") is True
    assert safe_regex.safe_search(r"\bnpm\b", "run pnpm install") is False
    # an invalid pattern fails safe (None), never raises
    assert safe_regex.safe_search(r"(", "anything") is None


def test_safe_search_returns_none_on_timeout(monkeypatch):
    # simulate a slow match (a real exponential regex would spin a thread; this does not)
    def slow(*_a, **_k):
        time.sleep(0.5)
        return object()

    monkeypatch.setattr(safe_regex.re, "search", slow)
    start = time.perf_counter()
    result = safe_regex.safe_search("x", "y", timeout=0.1)
    elapsed = time.perf_counter() - start
    assert result is None            # undecided within the bound -> fail-safe
    assert elapsed < 0.4             # returned at the bound, did not wait for the match


def test_enforce_regex_still_fires_and_fails_open():
    # normal deny-on-match still works through the safe path
    assert enforce._check("run npm install", "regex", r"\bnpm\b") is True
    assert enforce._check("run pnpm install", "regex", r"\bnpm\b") is False
    # not_regex (presence-required) still works
    assert enforce._check("fix the bug", "not_regex", r"[A-Z]+-[0-9]+") is True
    assert enforce._check("fix ABC-123", "not_regex", r"[A-Z]+-[0-9]+") is False
    # an invalid pattern never fires (fail open), never raises
    assert enforce._check("anything", "regex", r"(") is False
