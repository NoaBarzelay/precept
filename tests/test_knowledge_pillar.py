"""Knowledge-pillar tests over a TMP fixture vault (never the real, private vault).

Covers: index build + FTS5 BM25 ranking; empirical convention derivation;
audit findings + inbound_link_refs; and apply_plan's default-dry-run safety, the
rename + inbound-link rewrite, and the type:note skip (unless include_notes=True).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precept.knowledge import audit as kaudit
from precept.knowledge import config as kconfig
from precept.knowledge import conventions as kconv
from precept.knowledge import index as kindex


def _write(vault: Path, rel: str, body: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def vault(tmp_path) -> Path:
    """A small, well-formed fixture vault that follows the house conventions, plus a
    few deliberately planted violations the audit tests target."""
    v = tmp_path / "vault"
    v.mkdir()
    # Clean knowledge files (Title Case, spaces, English, type + Sources).
    _write(v, "Career/VC/Bessemer Venture Partners.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Bessemer Venture Partners\n\n"
           "Bessemer is a venture firm. See [[Index Ventures]] for a peer.\n\n## Sources\n- x\n")
    _write(v, "Career/VC/Index Ventures.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Index Ventures\n\n"
           "Index is a venture capital firm in London.\n\n## Sources\n- y\n")
    _write(v, "Personal/Keto Macros.md",
           "---\ntype: note\n---\n# Keto Macros\n\nFat protein carbs tracking for keto.\n")
    # Exempt system folder — never audited for frontmatter/naming.
    _write(v, "Claude/some_system_file.md", "# whatever\n\nsystem content\n")
    return v


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "state" / "knowledge_index.db"


# --- index + FTS5 search ----------------------------------------------------
def test_index_build_and_fts_ranking(vault, db):
    n = kindex.build(vault, db)
    assert n == 4  # all four .md files indexed (exempt folder is still indexed for search)

    hits = kindex.search(db, "bessemer venture", k=5)
    assert hits, "expected a match for 'bessemer venture'"
    assert hits[0]["title"] == "Bessemer Venture Partners"

    # Ranking: a query strongly about Index should rank Index Ventures first.
    hits = kindex.search(db, "London venture capital", k=5)
    assert hits[0]["title"] == "Index Ventures"


def test_index_records_links_and_inbound_count(vault, db):
    kindex.build(vault, db)
    # Bessemer links to [[Index Ventures]] -> Index has one inbound ref.
    assert kindex.inbound_link_count(db, "Index Ventures") == 1
    assert kindex.inbound_link_count(db, "Bessemer Venture Partners") == 0


def test_index_is_atomic_rebuild(vault, db):
    kindex.build(vault, db)
    first = kindex.search(db, "bessemer", k=5)
    # Rebuild over the live file: still complete, no leftover temp/wal.
    kindex.build(vault, db)
    second = kindex.search(db, "bessemer", k=5)
    assert first[0]["path"] == second[0]["path"]
    assert not db.with_name("." + db.name + ".build." + str(__import__("os").getpid())).exists()


# --- convention derivation --------------------------------------------------
def test_suggest_from_vault_derives_house_spec(vault):
    spec, stats = kconv.suggest_from_vault(vault)
    # The clean fixture (majority compliant) yields the documented house spec.
    assert spec.spaces_not_underscores is True
    assert spec.title_case is True
    assert spec.english_only is True
    assert spec.no_date_suffix is True
    assert spec.require_type_frontmatter is True
    assert spec.knowledge_requires_sources is True
    # Stats are reported as evidence; the exempt Claude/ file is counted in total but
    # not in non_exempt frontmatter checks.
    assert stats.total == 4
    assert stats.non_exempt == 3
    assert stats.knowledge_count == 2


def test_suggest_counts_planted_violations(vault):
    # Plant a date-suffixed, underscored, non-English file before deriving.
    _write(vault, "Career/VC/old_research_2026-05-01.md",
           "---\ntype: note\n---\n# old research\n\nbody\n")
    _write(vault, "Personal/מטבח.md", "---\ntype: note\n---\n# kitchen\n\nbody\n")
    _spec, stats = kconv.suggest_from_vault(vault)
    assert stats.with_underscore >= 1
    assert stats.with_date_suffix >= 1
    assert stats.non_ascii >= 1


# --- audit ------------------------------------------------------------------
def test_audit_flags_underscore_date_and_non_english(vault):
    # Planted: underscores + date suffix on a knowledge file that ALSO links nowhere,
    # but IS linked to from another file (inbound count).
    _write(vault, "Career/VC/legacy_fund_2026-05-01.md",
           "---\ntype: knowledge\nupdated: 2026-05-01\n---\n# legacy fund\n\nbody\n\n## Sources\n- z\n")
    # Two inbound references to [[legacy_fund_2026-05-01]].
    _write(vault, "Career/VC/Ref One.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Ref One\n\nsee [[legacy_fund_2026-05-01]]\n\n## Sources\n- a\n")
    _write(vault, "Career/VC/Ref Two.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Ref Two\n\nalso [[legacy_fund_2026-05-01|alias]]\n\n## Sources\n- b\n")
    # A non-English filename.
    _write(vault, "Personal/מטבח.md", "---\ntype: note\n---\n# kitchen\n\nbody\n")

    spec, _ = kconv.suggest_from_vault(vault)
    findings = kaudit.audit(vault, spec)
    by_path = {f.path: f for f in findings if f.kind == kaudit.FindingKind.RENAME}

    legacy = by_path["Career/VC/legacy_fund_2026-05-01.md"]
    reasons = set(legacy.reasons)
    assert kaudit.RenameReason.UNDERSCORE in reasons
    assert kaudit.RenameReason.DATE_SUFFIX in reasons
    assert legacy.inbound_link_refs == 2  # Ref One + Ref Two
    assert legacy.proposed_stem == "Legacy Fund"  # date stripped, underscores->spaces, Title Case

    heb = by_path["Personal/מטבח.md"]
    assert kaudit.RenameReason.NON_ENGLISH in heb.reasons
    assert heb.proposed_stem is None  # translation left as a TODO, never hardcoded
    assert heb.todo


def test_audit_flags_missing_frontmatter_and_sources(vault):
    _write(vault, "Career/Notes Without Type.md", "# Notes Without Type\n\nno frontmatter here\n")
    _write(vault, "Career/Knowledge No Sources.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Knowledge No Sources\n\nbody, no sources section\n")
    spec, _ = kconv.suggest_from_vault(vault)
    findings = kaudit.audit(vault, spec)
    kinds = {(f.kind, f.path) for f in findings}
    assert (kaudit.FindingKind.MISSING_FRONTMATTER, "Career/Notes Without Type.md") in kinds
    assert (kaudit.FindingKind.MISSING_SOURCES, "Career/Knowledge No Sources.md") in kinds


def test_audit_detects_date_strip_collision(vault):
    # Two files in the same folder collapse to the same base when the date is stripped.
    _write(vault, "Career/VC/Acme Corp.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Acme Corp\n\nbody\n\n## Sources\n- a\n")
    _write(vault, "Career/VC/Acme Corp 2026-05-01.md",
           "---\ntype: knowledge\nupdated: 2026-05-01\n---\n# Acme Corp\n\nbody\n\n## Sources\n- b\n")
    spec, _ = kconv.suggest_from_vault(vault)
    findings = kaudit.audit(vault, spec)
    dated = next(f for f in findings if f.path == "Career/VC/Acme Corp 2026-05-01.md"
                 and f.kind == kaudit.FindingKind.RENAME)
    assert dated.collision is True


# --- apply_plan -------------------------------------------------------------
def _plan_for(vault: Path, rel: str):
    spec, _ = kconv.suggest_from_vault(vault)
    findings = kaudit.audit(vault, spec)
    return kaudit.plan_from_findings([f for f in findings if f.path == rel])


def test_apply_plan_dry_run_changes_nothing(vault):
    target = "Career/VC/legacy_fund.md"
    _write(vault, target,
           "---\ntype: knowledge\nupdated: 2026-05-01\n---\n# legacy fund\n\nbody\n\n## Sources\n- z\n")
    _write(vault, "Career/VC/Linker.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Linker\n\nsee [[legacy_fund]]\n\n## Sources\n- a\n")
    before = {p: p.read_text() for p in vault.rglob("*.md")}
    plan = _plan_for(vault, target)
    assert plan, "expected a rename plan item"

    res = kaudit.apply_plan(plan, vault)  # default dry_run=True
    assert res.dry_run is True
    assert res.renamed  # it REPORTS what it would do
    after = {p: p.read_text() for p in vault.rglob("*.md")}
    assert before == after  # ...but nothing on disk changed
    assert (vault / target).exists()


def test_apply_plan_applied_renames_and_rewrites_links(vault):
    target = "Career/VC/legacy_fund.md"
    _write(vault, target,
           "---\ntype: knowledge\nupdated: 2026-05-01\n---\n# legacy fund\n\nbody\n\n## Sources\n- z\n")
    linker = _write(vault, "Career/VC/Linker.md",
                    "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Linker\n\nsee [[legacy_fund]] here\n\n## Sources\n- a\n")
    plan = _plan_for(vault, target)
    res = kaudit.apply_plan(plan, vault, dry_run=False)

    assert res.dry_run is False
    assert ("Career/VC/legacy_fund.md", "Career/VC/Legacy Fund.md") in res.renamed
    assert not (vault / target).exists()
    assert (vault / "Career/VC/Legacy Fund.md").exists()
    # Inbound [[legacy_fund]] -> [[Legacy Fund]] rewritten.
    assert "[[Legacy Fund]]" in linker.read_text()
    assert "[[legacy_fund]]" not in linker.read_text()
    assert res.links_rewritten == 1


def test_apply_plan_skips_notes_unless_included(vault):
    # A type:note file with a mechanical rename reason (underscore).
    note = _write(vault, "Personal/my_private_note.md",
                  "---\ntype: note\n---\n# my private note\n\nthe user's own thinking\n")
    plan = _plan_for(vault, "Personal/my_private_note.md")
    assert plan, "expected a rename plan item for the note"

    # Default: notes are SKIPPED even on an applied run.
    res = kaudit.apply_plan(plan, vault, dry_run=False)
    assert "Personal/my_private_note.md" in res.skipped_notes
    assert res.renamed == []
    assert note.exists()  # untouched

    # Opt-in: include_notes=True renames it.
    res2 = kaudit.apply_plan(plan, vault, dry_run=False, include_notes=True)
    assert res2.renamed == [("Personal/my_private_note.md", "Personal/My Private Note.md")]
    assert not note.exists()
    assert (vault / "Personal/My Private Note.md").exists()


# --- config -----------------------------------------------------------------
def test_config_resolves_vault_from_arg_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PRECEPT_VAULT", raising=False)
    with pytest.raises(ValueError):
        kconfig.resolve_vault(None)  # no default vault literal — must be supplied

    v = tmp_path / "v"
    v.mkdir()
    monkeypatch.setenv("PRECEPT_VAULT", str(v))
    assert kconfig.resolve_vault(None) == v.resolve()
    # Explicit arg wins over env.
    other = tmp_path / "other"
    other.mkdir()
    assert kconfig.resolve_vault(str(other)) == other.resolve()


def test_typography_and_foreign_letters_are_distinguished(tmp_path):
    """Em dashes are typographic (mechanical fix), not 'non-English'; only real foreign
    letters (Hebrew) are routed to translation. Brand casing (dltHub) is preserved."""
    v = tmp_path / "vault"
    v.mkdir()
    _write(v, "Career/David Frankel — Deep Research Brief — 2026-04-02.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# Brief\n\n## Sources\n- x\n")
    _write(v, "Personal/חברים.md", "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# x\n## Sources\n- x\n")
    _write(v, "Career/dltHub.md", "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# dltHub\n## Sources\n- x\n")

    # unit helpers
    assert not kconv.has_foreign_letters("David Frankel — Brief")
    assert kconv.has_typographic("David Frankel — Brief")
    assert kconv.has_foreign_letters("חברים")
    assert kconv.is_title_case("dltHub")  # intentional interior caps -> already valid
    assert kaudit.normalize_stem("Foo — Bar — 2026-04-02") == "Foo - Bar"

    findings = {f.path: f for f in kaudit.audit(v) if f.kind.name == "RENAME"}
    em = findings["Career/David Frankel — Deep Research Brief — 2026-04-02.md"]
    assert kaudit.RenameReason.NON_ENGLISH not in em.reasons      # not foreign
    assert kaudit.RenameReason.TYPOGRAPHIC in em.reasons          # mechanical
    assert em.proposed_stem == "David Frankel - Deep Research Brief"
    heb = findings["Personal/חברים.md"]
    assert kaudit.RenameReason.NON_ENGLISH in heb.reasons
    assert heb.proposed_stem is None                              # needs AI translation


def test_case_only_rename_is_not_a_collision(tmp_path):
    """A Title-Case-only rename must apply, not be skipped as a collision (the bug a
    case-insensitive filesystem caused on the real vault)."""
    v = tmp_path / "vault"
    v.mkdir()
    _write(v, "CBS/summer startup track.md",
           "---\ntype: knowledge\nupdated: 2026-05-28\n---\n# x\n## Sources\n- x\n")
    # Use an explicit spec so the one-file derivation doesn't switch title_case off.
    findings = kaudit.audit(v, kconv.ConventionSpec())
    plan = kaudit.plan_from_findings(findings)
    res = kaudit.apply_plan(plan, v, dry_run=True, include_notes=True)
    newnames = [n for _, n in res.renamed]
    assert "CBS/Summer Startup Track.md" in newnames
    assert not res.skipped_collision
