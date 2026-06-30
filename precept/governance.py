"""Rule governance (item 6): decay, supersede, conflict-detection.

The self-improvement pillar. Every operation here PROPOSES — it never auto-applies. A
proposal is surfaced (`precept govern`) and only takes effect when a human acts on it
(`apply_decay` / `apply_supersede`), keeping the PENDING-gate discipline intact:

  - decay:    a rule whose `fire_count` has stayed 0 past a threshold is proposed for
              RETIREMENT (-> status=ARCHIVED, never hard-deleted, so it's recoverable).
  - supersede: a newer rule REPLACES an older one — the old is ARCHIVED with a
              `superseded_by` back-pointer and the new gets a `supersedes` forward-pointer.
  - conflict: two ACTIVE rules that CONTRADICT, detected via the SAME LLM-judge seam used
              elsewhere (an injectable `verdict_fn`, so the eval stays deterministic and
              fail-OPEN — a model hiccup never proposes retiring a real rule).

Compile already excludes non-ACTIVE lessons from both the hook cache and the native
permission block, so an ARCHIVED rule stops enforcing the moment it's archived + recompiled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Callable, Optional

from . import catalog
from .models import Lesson, Status

# A rule that has never fired for this many days since creation is proposed for decay.
DEFAULT_DECAY_DAYS = 30

# verdict_fn(rule_a_text, rule_b_text) -> {"conflicts": bool, "reason": str} | None
ConflictFn = Callable[[str, str], Optional[dict]]


@dataclass
class DecayProposal:
    lesson_id: str
    age_days: int
    reason: str


@dataclass
class ConflictProposal:
    lesson_a: str
    lesson_b: str
    reason: str


def _rule_text(le: Lesson) -> str:
    return f"{le.trigger}: {le.what_to_do_instead} (was wrong: {le.what_was_wrong})"


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------
def propose_decay(
    lessons: list[Lesson] | None = None,
    *,
    threshold_days: int = DEFAULT_DECAY_DAYS,
    today: _date | None = None,
) -> list[DecayProposal]:
    """ACTIVE rules that have never fired (fire_count==0) and are older than the
    threshold are proposed for retirement. PENDING/ARCHIVED rules are out of scope (a
    PENDING rule was never enforced, so 'never fired' is not evidence it's dead)."""
    lessons = catalog.load_all() if lessons is None else lessons
    today = today or _date.today()
    out: list[DecayProposal] = []
    for le in lessons:
        if le.status != Status.ACTIVE or le.signals.fire_count > 0:
            continue
        age = (today - le.created).days
        if age >= threshold_days:
            out.append(DecayProposal(
                le.id, age,
                f"active {age}d, never fired (fire_count=0) — propose retiring",
            ))
    return out


def apply_decay(lesson_id: str) -> Lesson:
    """Retire a rule: ARCHIVED (recoverable), never hard-deleted. Caller recompiles."""
    le = _load_one(lesson_id)
    le.status = Status.ARCHIVED
    catalog.write(le)
    return le


# ---------------------------------------------------------------------------
# Supersede
# ---------------------------------------------------------------------------
def apply_supersede(old_id: str, new_id: str) -> tuple[Lesson, Lesson]:
    """A newer rule replaces an older one: the OLD is ARCHIVED with a `superseded_by`
    back-pointer; the NEW records `supersedes`. Nothing is hard-deleted. Caller recompiles."""
    if old_id == new_id:
        raise ValueError("a rule cannot supersede itself")
    old = _load_one(old_id)
    new = _load_one(new_id)
    old.status = Status.ARCHIVED
    old.superseded_by = new.id
    new.supersedes = old.id
    catalog.write(old)
    catalog.write(new)
    return old, new


# ---------------------------------------------------------------------------
# Conflict detection (the LLM-judge piece — injectable, fail-open)
# ---------------------------------------------------------------------------
def detect_conflicts(
    lessons: list[Lesson] | None = None,
    verdict_fn: ConflictFn | None = None,
) -> list[ConflictProposal]:
    """Compare every pair of ACTIVE rules and propose the contradictory ones.

    `verdict_fn(text_a, text_b) -> {"conflicts": bool, "reason": str} | None` is the
    injection seam (tests/eval pass a fake; production uses the real judge). FAIL-OPEN:
    a None verdict is treated as 'no conflict' so a model hiccup never proposes a conflict."""
    lessons = catalog.load_all() if lessons is None else lessons
    active = [le for le in lessons if le.status == Status.ACTIVE]
    vf = verdict_fn or _default_conflict_fn
    out: list[ConflictProposal] = []
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            v = vf(_rule_text(a), _rule_text(b))
            if v and v.get("conflicts"):
                out.append(ConflictProposal(a.id, b.id, v.get("reason", "")))
    return out


def _default_conflict_fn(text_a: str, text_b: str) -> dict | None:
    """Production conflict verdict via the lazy judge (keeps governance import light)."""
    from . import judge

    v = judge.conflict_verdict(text_a, text_b)
    if v is None:
        return None
    return {"conflicts": v.conflicts, "reason": v.reason}


# ---------------------------------------------------------------------------
def _load_one(lesson_id: str) -> Lesson:
    for le in catalog.load_all():
        if le.id == lesson_id:
            return le
    raise KeyError(f"no lesson with id '{lesson_id}'")
