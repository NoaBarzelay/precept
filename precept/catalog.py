"""The auditable catalog: one markdown card per Lesson, the source of truth.

Frontmatter carries every structured field (so parsing is exact and lossless);
the body is a human-readable rendering. Cards are written atomically. The catalog
dir is git-init'd elsewhere so `git log -- <card>.md` is the lifecycle audit trail.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import paths
from .models import Lesson
from .safety import atomic_write_text

_FM = "---"


def card_path(lesson_id: str) -> Path:
    return paths.catalog_dir() / f"{lesson_id}.md"


def render(lesson: Lesson) -> str:
    """Lesson -> markdown card (YAML frontmatter is the source of truth + a body)."""
    data = lesson.model_dump(mode="json", exclude={"policies"})
    data["policies"] = [p.model_dump(mode="json", exclude_none=True) for p in lesson.policies]
    front = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    body = (
        f"# {lesson.trigger}\n\n"
        f"**What was wrong:** {lesson.what_was_wrong}\n\n"
        f"**Do instead:** {lesson.what_to_do_instead}\n"
    )
    if lesson.origin_quote:
        body += f"\n> {lesson.origin_quote}\n"
    return f"{_FM}\n{front}\n{_FM}\n\n{body}"


def parse(text: str) -> Lesson:
    """Markdown card -> Lesson (frontmatter is authoritative; body is ignored)."""
    if not text.startswith(_FM):
        raise ValueError("card is missing YAML frontmatter")
    _, front, *_ = text.split(_FM, 2)
    data = yaml.safe_load(front)
    return Lesson.model_validate(data)


def write(lesson: Lesson) -> Path:
    paths.ensure_dirs()
    p = card_path(lesson.id)
    atomic_write_text(p, render(lesson))
    return p


def read(path: Path) -> Lesson:
    return parse(Path(path).read_text(encoding="utf-8"))


def load_all() -> list[Lesson]:
    d = paths.catalog_dir()
    if not d.exists():
        return []
    out: list[Lesson] = []
    for p in sorted(d.glob("*.md")):
        try:
            out.append(read(p))
        except Exception:  # tolerate a stray/old card; never hard-fail the whole catalog
            continue
    return out
