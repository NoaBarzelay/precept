"""Convention spec — the naming/structure rules the vault is held to, DERIVED
empirically from the vault itself rather than hardcoded.

`suggest_from_vault` scans the real files and reports both the spec (a set of boolean
expectations) and the supporting stats, so the rules are evidence-backed: "spaces not
underscores" is asserted because the overwhelming majority of existing files already
use spaces, etc. The spec is then what `audit` holds files to.

The fixed conventions (from the vault convention doc) this slice encodes:
  - filenames use SPACES, not underscores
  - Title Case
  - English-only (flag non-ASCII / non-English)
  - NO date suffix (e.g. trailing `YYYY-MM-DD`)
  - `type:` frontmatter required OUTSIDE the exempt folders (Claude/, Claude Conversations/)
  - knowledge files require a `## Sources` section
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter
from .index import EXEMPT_FOLDERS, iter_markdown

# A trailing date suffix like " — 2026-05-28" or "-2026-05-28" or " 2026-05-28".
_DATE_SUFFIX = re.compile(r"[ \-—_]+\d{4}-\d{2}-\d{2}\s*$")
_UNDERSCORE = re.compile(r"_")
# Typographic chars to normalize to ASCII in a filename (the vault convention bans em
# dashes; curly quotes / ellipsis likewise). These are NOT "non-English" — they are
# punctuation, fixed by a mechanical rename, not by translation.
_TYPO_MAP = {
    "—": "-", "–": "-",   # em / en dash -> hyphen
    "‘": "'", "’": "'",   # curly single quotes -> straight
    "“": '"', "”": '"',   # curly double quotes -> straight
    "…": "...",                 # ellipsis -> three dots
}
# Small words that stay lowercase in Title Case (other than at the start).
_TITLE_MINOR = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "nor", "of", "on", "or", "per", "than", "the", "to", "via", "vs", "with", "x",
}
# Brand/product names that are intentionally all-lowercase (no interior capital to key
# on): kept as-is rather than Title-Cased or flagged. Alphanumeric brands like `a16z`
# are also covered by the digit rule below.
_LOWER_BRANDS = {"npm", "a16z"}
# A lowercase-hyphenated "slug" filename (e.g. an imported web page,
# `playbook-the-ai-kill-chain`). These mirror external source URLs and are left as-is.
_IMPORT_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


@dataclass
class ConventionSpec:
    """The expectations a vault filename/file is held to. Booleans so the audit can
    flip any rule off for a vault that empirically doesn't follow it."""

    spaces_not_underscores: bool = True
    title_case: bool = True
    english_only: bool = True
    no_date_suffix: bool = True
    require_type_frontmatter: bool = True
    knowledge_requires_sources: bool = True
    exempt_folders: tuple[str, ...] = EXEMPT_FOLDERS


@dataclass
class ConventionStats:
    """Supporting counts behind the derived spec (the evidence)."""

    total: int = 0
    non_exempt: int = 0
    with_underscore: int = 0
    with_date_suffix: int = 0
    non_ascii: int = 0
    non_latin: int = 0        # contains a real foreign letter (drives english_only)
    typographic: int = 0      # contains non-ASCII punctuation (em dash, curly quote)
    not_title_case: int = 0
    missing_type: int = 0
    knowledge_count: int = 0
    knowledge_missing_sources: int = 0
    per_folder: dict[str, int] = field(default_factory=dict)


def is_ascii(text: str) -> bool:
    return all(ord(c) < 128 for c in text)


def has_foreign_letters(text: str) -> bool:
    """True if the text contains a LETTER outside ASCII (a real non-English script like
    Hebrew). This is what 'non-English' means for the audit — as opposed to mere
    typographic punctuation (em dash, curly quotes), which is NOT foreign and is fixed
    mechanically, not translated."""
    return any(c.isalpha() and ord(c) > 127 for c in text)


def has_typographic(text: str) -> bool:
    """True if the text contains a non-ASCII char that is NOT a letter (em/en dash,
    curly quote, ellipsis): a mechanical normalization to ASCII, not a translation."""
    return any(ord(c) > 127 and not c.isalpha() for c in text)


def normalize_typography(text: str) -> str:
    for k, v in _TYPO_MAP.items():
        text = text.replace(k, v)
    return text


def is_title_case(stem: str) -> bool:
    """A pragmatic Title Case check tolerant of real titles: every significant word
    starts uppercase (minor words may be lowercase mid-title); tokens with no letters
    (numbers, standalone punctuation) and ALL-CAPS acronyms are allowed."""
    words = re.split(r"[ \-—]+", stem.strip())
    words = [w for w in words if w]
    if not words:
        return False
    for i, w in enumerate(words):
        core = re.sub(r"[^\w]", "", w)
        if not core or not core[0].isalpha():
            continue  # numbers / symbols — nothing to capitalize
        if any(c.isupper() for c in core[1:]):
            continue  # intentional internal caps (dltHub, iPhone, gRPC, macOS) — valid
        if any(c.isdigit() for c in core):
            continue  # alphanumeric identifier/version token (a16z, v6, gpt4) — valid
        low = core.lower()
        if low in _LOWER_BRANDS:
            continue  # known all-lowercase brand (npm)
        if i != 0 and low in _TITLE_MINOR:
            continue  # minor word allowed lowercase mid-title
        if not core[0].isupper():
            return False
    return True


def is_import_slug(stem: str) -> bool:
    """Lowercase-hyphenated slug filename (imported web content). Mirrors source URLs;
    left as-is, so the auditor does not propose renaming it."""
    return bool(_IMPORT_SLUG.fullmatch(stem))


def has_date_suffix(stem: str) -> bool:
    return _DATE_SUFFIX.search(stem) is not None


def is_exempt(folder: str, exempt: tuple[str, ...]) -> bool:
    """A folder (vault-relative posix) is exempt if it is, or is under, an exempt root."""
    top = folder.split("/", 1)[0] if folder else ""
    return top in exempt


def suggest_from_vault(vault: str | Path) -> tuple[ConventionSpec, ConventionStats]:
    """Scan the vault and DERIVE the convention spec empirically, returning the spec
    plus the stats that back it. The spec keeps a rule ON when the vault majority
    already complies (so the audit enforces the house style), and reports the raw
    counts so the caller can see the evidence."""
    vault = Path(vault)
    stats = ConventionStats()
    for path in iter_markdown(vault):
        stats.total += 1
        rel_folder = path.parent.relative_to(vault).as_posix()
        rel_folder = "" if rel_folder == "." else rel_folder
        stats.per_folder[rel_folder] = stats.per_folder.get(rel_folder, 0) + 1
        exempt = is_exempt(rel_folder, EXEMPT_FOLDERS)
        stem = path.stem

        if _UNDERSCORE.search(stem):
            stats.with_underscore += 1
        if has_date_suffix(stem):
            stats.with_date_suffix += 1
        if not is_ascii(stem):
            stats.non_ascii += 1
        if has_foreign_letters(stem):
            stats.non_latin += 1
        if has_typographic(stem):
            stats.typographic += 1
        if not is_title_case(stem):
            stats.not_title_case += 1

        if exempt:
            continue
        stats.non_exempt += 1
        try:
            meta, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not meta.get("type"):
            stats.missing_type += 1
        if meta.get("type") == "knowledge":
            stats.knowledge_count += 1
            if not frontmatter.has_sources_section(body):
                stats.knowledge_missing_sources += 1

    # The spec is derived: a rule is asserted when the vault MAJORITY already complies
    # (compliant filenames > violating ones). A brand-new/empty vault keeps the defaults
    # (the documented house style). This makes the rules evidence-backed, not imposed.
    def majority_ok(violations: int, universe: int) -> bool:
        if universe == 0:
            return True
        return violations <= universe / 2

    spec = ConventionSpec(
        spaces_not_underscores=majority_ok(stats.with_underscore, stats.total),
        title_case=majority_ok(stats.not_title_case, stats.total),
        english_only=majority_ok(stats.non_latin, stats.total),
        no_date_suffix=majority_ok(stats.with_date_suffix, stats.total),
        require_type_frontmatter=majority_ok(stats.missing_type, stats.non_exempt),
        knowledge_requires_sources=majority_ok(
            stats.knowledge_missing_sources, stats.knowledge_count
        ),
    )
    return spec, stats
