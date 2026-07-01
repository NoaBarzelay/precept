"""The integrity auditor — and the renamer.

`audit(vault, spec)` walks the vault and returns typed `Finding`s: rename proposals
(with a reason and the inbound [[link]] blast-radius), missing-frontmatter,
missing-sources-section, misplacement candidates, and date-suffix-strip COLLISIONS.

`apply_plan(plan, vault, dry_run=True)` is the executor. It DEFAULTS to dry-run (it
never mutates the vault unless explicitly told to), and when applied it renames the
file AND rewrites every inbound `[[oldstem]]` -> `[[newstem]]` across the vault, each
write atomic. It SKIPS `type: note` files unless `include_notes=True` — Claude must
never rename the user's own note files without an explicit opt-in.

Non-English names are flagged but NOT auto-translated: the proposed English name is
left as a TODO for the caller/AI to fill (no hardcoded translation table).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..safety import atomic_write_text
from . import conventions, frontmatter
from .conventions import ConventionSpec
from .index import iter_markdown


class FindingKind(str, Enum):
    RENAME = "rename"
    MISSING_FRONTMATTER = "missing_frontmatter"
    MISSING_SOURCES = "missing_sources"
    MISPLACEMENT = "misplacement"


class RenameReason(str, Enum):
    NON_ENGLISH = "non_english"
    TYPOGRAPHIC = "typographic"   # non-ASCII punctuation (em dash, curly quote) -> ASCII
    DATE_SUFFIX = "date_suffix"
    UNDERSCORE = "underscore"
    NOT_TITLE_CASE = "not_title_case"


@dataclass
class Finding:
    """One auditor result. For RENAME findings, `proposed_stem` is the suggested new
    filename stem (sans `.md`); for a NON_ENGLISH rename it is left None with a TODO,
    because translation is the caller/AI's job, not a hardcoded table here."""

    kind: FindingKind
    path: str                          # vault-relative posix path of the offending file
    reasons: list[RenameReason] = field(default_factory=list)
    proposed_stem: str | None = None   # new stem for a RENAME (None => needs AI fill)
    todo: str | None = None            # human/AI action note (e.g. "translate to English")
    inbound_link_refs: int = 0         # how many other files contain [[oldstem]]
    collision: bool = False            # stripping a date suffix would collide in-folder
    detail: str = ""                   # free-text context (misplacement, etc.)
    doc_type: str | None = None        # the file's frontmatter type (note/knowledge/None)


# --- name normalization -----------------------------------------------------
def normalize_stem(stem: str) -> str:
    """Best-effort English-name normalization for the mechanical fixes (underscore /
    date-suffix / title-case). Non-English content is NOT translated here."""
    s = conventions._DATE_SUFFIX.sub("", stem)   # drop a trailing date suffix
    s = conventions.normalize_typography(s)       # em dash / curly quotes -> ASCII
    s = s.replace("_", " ")                       # underscores -> spaces
    s = re.sub(r"\s+", " ", s).strip()
    return _to_title_case(s)


def _to_title_case(stem: str) -> str:
    parts = re.split(r"(\s+|-|—)", stem)  # keep the separators
    out: list[str] = []
    word_index = 0
    for tok in parts:
        if not tok or re.fullmatch(r"\s+|-|—", tok):
            out.append(tok)
            continue
        core = re.sub(r"[^\w]", "", tok)
        if core and any(c.isupper() for c in core[1:]):
            out.append(tok)  # intentional internal caps (dltHub, iPhone, gRPC) — keep
        elif core and core.isupper() and len(core) > 1:
            out.append(tok)  # keep acronyms (VC, AI, ...) as-is
        elif word_index != 0 and tok.lower() in conventions._TITLE_MINOR:
            out.append(tok.lower())
        else:
            out.append(tok[:1].upper() + tok[1:])
        word_index += 1
    return "".join(out)


# --- inbound link counting (vault-wide, no DB dependency) -------------------
def _wikilink_re(stem: str) -> re.Pattern[str]:
    """Match `[[stem]]`, `[[stem|alias]]`, `[[stem#anchor]]` for an exact stem."""
    return re.compile(r"\[\[" + re.escape(stem) + r"(?=[\]|#])")


def count_inbound_links(vault: Path, stem: str, exclude: Path | None = None) -> int:
    """Count DISTINCT files (other than `exclude`) that contain a [[stem]] reference.
    Vault-wide scan (the audit is a one-shot integrity pass; it doesn't require the
    index to be fresh)."""
    pat = _wikilink_re(stem)
    n = 0
    for path in iter_markdown(vault):
        if exclude is not None and path == exclude:
            continue
        try:
            if pat.search(path.read_text(encoding="utf-8", errors="replace")):
                n += 1
        except OSError:
            continue
    return n


# --- the audit --------------------------------------------------------------
def audit(vault: str | Path, spec: ConventionSpec | None = None) -> list[Finding]:
    """Walk the vault and return all integrity findings under `spec` (derived from the
    vault when not supplied)."""
    vault = Path(vault)
    if spec is None:
        spec, _ = conventions.suggest_from_vault(vault)

    findings: list[Finding] = []
    # Pre-compute, per folder, the set of base stems (date-suffix stripped) to detect
    # collisions when a rename would strip a date suffix.
    stripped_by_folder: dict[str, dict[str, int]] = {}
    for path in iter_markdown(vault):
        folder = _rel_folder(vault, path)
        base = conventions._DATE_SUFFIX.sub("", path.stem)
        stripped_by_folder.setdefault(folder, {})
        stripped_by_folder[folder][base] = stripped_by_folder[folder].get(base, 0) + 1

    for path in iter_markdown(vault):
        rel = path.relative_to(vault).as_posix()
        folder = _rel_folder(vault, path)
        exempt = conventions.is_exempt(folder, spec.exempt_folders)
        stem = path.stem
        try:
            meta, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        doc_type = meta.get("type")

        # 1. Rename reasons (filename hygiene). Applies in every folder (filenames are
        #    a vault-wide convention), but the exempt system folders are skipped.
        if not exempt:
            reasons: list[RenameReason] = []
            if spec.english_only and conventions.has_foreign_letters(stem):
                reasons.append(RenameReason.NON_ENGLISH)
            if conventions.has_typographic(stem):
                reasons.append(RenameReason.TYPOGRAPHIC)
            if spec.no_date_suffix and conventions.has_date_suffix(stem):
                reasons.append(RenameReason.DATE_SUFFIX)
            if spec.spaces_not_underscores and "_" in stem:
                reasons.append(RenameReason.UNDERSCORE)
            if spec.title_case and not conventions.is_title_case(stem):
                reasons.append(RenameReason.NOT_TITLE_CASE)
            if reasons:
                findings.append(_rename_finding(vault, path, rel, folder, stem, reasons, doc_type, stripped_by_folder))

            # 2. Frontmatter / sources integrity (non-exempt only).
            if spec.require_type_frontmatter and not doc_type:
                findings.append(Finding(
                    kind=FindingKind.MISSING_FRONTMATTER, path=rel, doc_type=doc_type,
                    detail="no `type:` frontmatter (required outside exempt folders)",
                ))
            if spec.knowledge_requires_sources and doc_type == "knowledge" \
                    and not frontmatter.has_sources_section(body):
                findings.append(Finding(
                    kind=FindingKind.MISSING_SOURCES, path=rel, doc_type=doc_type,
                    detail="knowledge file is missing a `## Sources` section",
                ))
    return findings


def _rename_finding(
    vault: Path, path: Path, rel: str, folder: str, stem: str,
    reasons: list[RenameReason], doc_type: str | None,
    stripped_by_folder: dict[str, dict[str, int]],
) -> Finding:
    non_english = RenameReason.NON_ENGLISH in reasons
    proposed: str | None
    todo: str | None
    if non_english:
        proposed = None  # translation is the caller/AI's job — never hardcode one here
        todo = "translate filename to English (Title Case, no date suffix, spaces)"
    else:
        proposed = normalize_stem(stem)
        todo = None
        if proposed == stem:
            proposed = None  # nothing mechanical to change (shouldn't happen given reasons)

    # Collision: would stripping the date suffix land on an existing base in this folder?
    collision = False
    if RenameReason.DATE_SUFFIX in reasons:
        base = conventions._DATE_SUFFIX.sub("", stem)
        if stripped_by_folder.get(folder, {}).get(base, 0) > 1:
            collision = True

    return Finding(
        kind=FindingKind.RENAME, path=rel, reasons=reasons,
        proposed_stem=proposed, todo=todo,
        inbound_link_refs=count_inbound_links(vault, stem, exclude=path),
        collision=collision, doc_type=doc_type,
    )


def _rel_folder(vault: Path, path: Path) -> str:
    f = path.parent.relative_to(vault).as_posix()
    return "" if f == "." else f


# --- the executor (default-safe) --------------------------------------------
@dataclass
class RenamePlanItem:
    """One concrete rename to apply: old vault-relative path -> new filename stem."""

    path: str            # vault-relative posix path of the file to rename
    new_stem: str        # the new filename stem (no .md)
    doc_type: str | None = None


def plan_from_findings(findings: list[Finding]) -> list[RenamePlanItem]:
    """Turn the auto-fixable RENAME findings into a concrete plan. Findings with no
    proposed stem (non-English, awaiting AI translation) and collisions are EXCLUDED —
    those need a human/AI to supply a safe target first."""
    plan: list[RenamePlanItem] = []
    for f in findings:
        if f.kind != FindingKind.RENAME or f.proposed_stem is None or f.collision:
            continue
        plan.append(RenamePlanItem(path=f.path, new_stem=f.proposed_stem, doc_type=f.doc_type))
    return plan


@dataclass
class ApplyResult:
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old_rel, new_rel)
    links_rewritten: int = 0                                       # files whose links changed
    skipped_notes: list[str] = field(default_factory=list)        # note files skipped
    skipped_collision: list[str] = field(default_factory=list)
    dry_run: bool = True


def _rewrite_links_in_vault(
    vault: Path, old_stem: str, new_stem: str, *, apply: bool, skip: Path | None,
) -> int:
    """Rewrite every inbound `[[old_stem]]` -> `[[new_stem]]` across the vault (preserving
    aliases/anchors). Returns the count of files that contained a reference. Each changed
    file is rewritten atomically. When `apply` is False, only counts."""
    pat = _wikilink_re(old_stem)
    replacement = "[[" + new_stem
    changed = 0
    for path in iter_markdown(vault):
        if skip is not None and path == skip:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not pat.search(text):
            continue
        changed += 1
        if apply:
            atomic_write_text(path, pat.sub(replacement, text))
    return changed


def apply_plan(
    plan: list[RenamePlanItem], vault: str | Path, *,
    dry_run: bool = True, include_notes: bool = False,
) -> ApplyResult:
    """Execute a rename plan. DEFAULT dry-run (never mutates the vault unless dry_run is
    explicitly False). For each item it renames the file (atomic os.replace) and rewrites
    inbound [[oldstem]] -> [[newstem]] vault-wide.

    SAFETY: a `type: note` file is SKIPPED unless `include_notes=True` (Claude must not
    rename the user's own notes without an explicit opt-in). A target that already exists is
    skipped as a collision (never clobber)."""
    vault = Path(vault)
    res = ApplyResult(dry_run=dry_run)
    for item in plan:
        src = vault / item.path
        if not src.exists():
            continue
        # Re-read the type from disk (the plan may carry a stale/None type).
        try:
            meta, _ = frontmatter.split(src.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        doc_type = meta.get("type") or item.doc_type
        if doc_type == "note" and not include_notes:
            res.skipped_notes.append(item.path)
            continue

        old_stem = src.stem
        if old_stem == item.new_stem:
            continue
        dst = src.with_name(item.new_stem + src.suffix)
        # A real collision is when `dst` exists AND is a DIFFERENT file. On a
        # case-insensitive filesystem (APFS) a pure case change ("foo" -> "Foo") makes
        # `dst.exists()` true while pointing at the SAME inode — that is not a collision.
        case_only = False
        if dst.exists() and dst != src:
            try:
                case_only = dst.samefile(src)
            except OSError:
                case_only = False
            if not case_only:
                res.skipped_collision.append(item.path)
                continue

        # Count (dry-run) or rewrite (apply) inbound links; then move the file.
        res.links_rewritten += _rewrite_links_in_vault(
            vault, old_stem, item.new_stem, apply=not dry_run, skip=src,
        )
        new_rel = dst.relative_to(vault).as_posix()
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if case_only:
                # Case-only rename on a case-insensitive FS needs a two-step move,
                # or os.replace is a no-op and the case never changes.
                tmp = src.with_name(item.new_stem + ".precept-rename-tmp" + src.suffix)
                src.replace(tmp)
                tmp.replace(dst)
            else:
                src.replace(dst)  # atomic within the same filesystem
        res.renamed.append((item.path, new_rel))
    return res
