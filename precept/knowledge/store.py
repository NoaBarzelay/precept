"""The vault-backed knowledge STORE — the ONE knowledge store (the `~/.precept/notes`
silo is retired into this).

A knowledge file is a markdown doc in the (private, configurable) vault: `type: knowledge`
frontmatter + an `updated:` date + a `## Sources` section, the house format the auditor
holds files to. Writing one is two steps, both safe:
  1. atomically write the markdown into the routed vault folder (source of truth);
  2. fold it into the LIVE derived index (incremental upsert), so recall sees it at once.

A freshly-CAPTURED file (mined from a session, not hand-filed) is marked PENDING with a
`precept_status: pending` frontmatter key — it is auto-written but NEEDS-CONFIRMATION, never
silently treated as final. The review surface (item 3, extended for knowledge) lists these.

STDLIB + pyyaml only; no network. The vault is resolved at runtime (PRECEPT_VAULT), never
bundled — the store never invents a vault path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from ..safety import atomic_write_text
from . import config as kconfig
from . import frontmatter
from . import index as kindex

# The folder a clearly-novel capture lands in when routing finds no good home, and the
# folder the legacy `precept note` lands in (a flat inbox the user can refile from).
DEFAULT_FOLDER = "Notes"
# Routing confidence below this => treat as a clearly-novel entity (propose a NEW folder)
# rather than forcing a poor fit into an existing one.
ROUTE_MIN_CONFIDENCE = 0.34

_PENDING_KEY = "precept_status"
_PENDING_VALUE = "pending"


@dataclass
class WriteResult:
    """The outcome of filing a knowledge file: where it landed, whether it is pending,
    and the routing confidence (0.0 => a new/forced folder, not a content match)."""

    path: Path                 # absolute path written
    rel: str                   # vault-relative posix path
    folder: str                # the (routed) folder it landed in
    pending: bool              # True => auto-captured, needs confirmation
    routed: bool               # True => folder chosen by content match (vs. default/explicit)
    confidence: float = 0.0


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return "-".join(s.split("-")[:8]) or "note"


def _title_filename(title: str) -> str:
    """A house-style filename stem from a title: spaces (not underscores), no date suffix,
    trimmed. We keep the title's own casing (the auditor's Title-Case check is tolerant)."""
    s = title.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r'[\\/:*?"<>|]', "", s)  # strip filesystem-illegal chars
    return s or "Note"


def render_knowledge(
    title: str, body: str, *, sources: list[str] | None = None,
    tags: list[str] | None = None, today: _date | None = None, pending: bool = False,
) -> str:
    """Render a well-formed knowledge file: `type: knowledge` + `updated:` (+ optional
    `precept_status: pending` and `tags`) frontmatter, an H1, the body, and a `## Sources`
    section (the auditor requires one on every knowledge file)."""
    updated = (today or _date.today()).isoformat()
    fm = ["---", "type: knowledge", f"updated: {updated}"]
    if pending:
        fm.append(f"{_PENDING_KEY}: {_PENDING_VALUE}")
    if tags:
        fm.append("tags: [" + ", ".join(tags) + "]")
    fm.append("---")
    src_lines = sources or []
    sources_block = "\n".join(f"- {s}" for s in src_lines) if src_lines else "- (none yet)"
    return (
        "\n".join(fm) + "\n\n"
        f"# {title}\n\n"
        f"{body.strip()}\n\n"
        f"## Sources\n{sources_block}\n"
    )


def is_pending(path: Path) -> bool:
    """True if a knowledge file is still PENDING confirmation (precept-captured)."""
    try:
        meta, _ = frontmatter.split(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return meta.get(_PENDING_KEY) == _PENDING_VALUE


def confirm(path: Path) -> None:
    """Promote a PENDING captured file to final: strip the `precept_status` line in place
    (atomic). No-op if the file isn't pending."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return
    new = re.sub(rf"(?m)^{_PENDING_KEY}:\s*{_PENDING_VALUE}\s*\n", "", text, count=1)
    if new != text:
        atomic_write_text(p, new)


def _unique_path(vault: Path, folder: str, stem: str) -> Path:
    """A non-clobbering target path: `<folder>/<stem>.md`, suffixing ` 2`, ` 3`… if taken."""
    base_dir = vault / folder if folder else vault
    candidate = base_dir / f"{stem}.md"
    i = 2
    while candidate.exists():
        candidate = base_dir / f"{stem} {i}.md"
        i += 1
    return candidate


def file_knowledge(
    title: str, body: str, *,
    vault: str | Path | None = None,
    db_path: Path | None = None,
    folder: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    pending: bool = False,
    auto_route: bool = True,
    today: _date | None = None,
) -> WriteResult:
    """Write a knowledge file into the vault and fold it into the live index.

    Routing: if `folder` is given it is used verbatim; otherwise, when `auto_route`, the
    title+body are matched against the existing index and the best-fitting EXISTING folder
    is chosen — but only when the match clears `ROUTE_MIN_CONFIDENCE`; below that we treat
    the file as a clearly-novel entity and land it in a NEW `DEFAULT_FOLDER` (proposing a
    new home rather than forcing a poor fit). Empty index => default folder.

    `pending=True` marks it needs-confirmation (the capture path). Returns a WriteResult."""
    v = kconfig.resolve_vault(vault)
    db = Path(db_path) if db_path is not None else kconfig.knowledge_index_db()

    routed = False
    confidence = 0.0
    chosen = folder
    if chosen is None:
        if auto_route:
            best, confidence = kindex.route_folder(db, title, body)
            if best is not None and best != "" and confidence >= ROUTE_MIN_CONFIDENCE:
                chosen = best
                routed = True
        if chosen is None:
            chosen = DEFAULT_FOLDER

    stem = _title_filename(title)
    target = _unique_path(v, chosen, stem)
    text = render_knowledge(
        title, body, sources=sources, tags=tags, today=today, pending=pending
    )
    atomic_write_text(target, text)
    kindex.upsert_file(db, v, target)

    rel = target.relative_to(v).as_posix()
    return WriteResult(
        path=target, rel=rel, folder=chosen, pending=pending,
        routed=routed, confidence=confidence,
    )
