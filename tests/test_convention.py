"""CONVENTION artifact: a kept SOFT convention is written into a Precept-owned
`.claude/rules/*.md` file — scoped by the lesson, idempotent, manifest-driven cleanup,
bootstrap directives NOT re-emitted, exact-inverse uninstall. All isolated to a temp
$PRECEPT_CLAUDE_HOME / $PRECEPT_STATE_DIR (no real config touched)."""

from datetime import date

import pytest

from precept import convention, compile as compile_mod, install
from precept.models import (
    ArtifactType, CheckKind, Determinism, EnforcementTier, HookEvent, Lesson, Origin,
    Policy, Scope, Status,
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    home.mkdir()
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(home))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    return home


def _conv(
    lid: str, do: str, *, scope=Scope.GLOBAL, scope_value=None,
    origin=Origin.CORRECTION, status=Status.ACTIVE,
) -> Lesson:
    le = Lesson(
        id=lid, created=date(2026, 6, 30), origin=origin, source_session="s",
        artifact_type=ArtifactType.CONVENTION, determinism=Determinism.STYLISTIC,
        scope=scope, scope_value=scope_value,
        trigger="t", what_was_wrong="w", what_to_do_instead=do,
    )
    le.status = status
    return le


# --- placement -------------------------------------------------------------
def test_target_global_is_user_rules_file(isolated):
    dest = convention.target_for(_conv("g", "prefer composition"))
    assert dest == isolated / "rules" / "precept-conventions.md"


def test_target_repo_is_project_rules_file(isolated, tmp_path):
    root = tmp_path / "proj"
    dest = convention.target_for(_conv("r", "x", scope=Scope.REPO, scope_value=str(root)))
    assert dest == root / ".claude" / "rules" / "precept-conventions.md"


def test_target_repo_without_root_is_unplaceable(isolated):
    assert convention.target_for(_conv("r", "x", scope=Scope.REPO)) is None


def test_target_language_is_marked_file(isolated):
    dest = convention.target_for(_conv("l", "type hints", scope=Scope.LANGUAGE, scope_value="python"))
    assert dest == isolated / "rules" / "precept-python.md"


# --- the write-back boundary ----------------------------------------------
def test_is_managed_excludes_bootstrap_pending_and_nonconvention(isolated):
    assert convention.is_managed(_conv("ok", "x")) is True
    # imported from the user's own CLAUDE.md -> already in context, never re-emitted
    assert convention.is_managed(_conv("b", "x", origin=Origin.BOOTSTRAP)) is False
    assert convention.is_managed(_conv("p", "x", status=Status.PENDING)) is False
    rule = _conv("rule", "x")
    rule.artifact_type = ArtifactType.RULE
    assert convention.is_managed(rule) is False
    # A convention that ALSO compiled to a HARD policy must NOT be double-written as soft.
    enforced = _conv("enforced", "x")
    enforced.policies = [Policy(
        id="enforced-p1", lesson_id="enforced", enforcement_tier=EnforcementTier.HARD,
        hook_event=HookEvent.STOP, check_kind=CheckKind.JUDGMENT, message="m",
        judgment_prompt="is it satisfied?",
    )]
    assert convention.is_managed(enforced) is False


# --- rendering -------------------------------------------------------------
def test_render_is_sorted_and_headed(isolated):
    text = convention.render_file([_conv("z", "second"), _conv("a", "first")])
    assert "managed by Precept" in text
    assert text.index("- first") < text.index("- second")  # sorted by id
    assert not text.startswith("---")  # no frontmatter for an unscoped file


def test_render_language_emits_paths_frontmatter(isolated):
    text = convention.render_file([_conv("l", "type hints")], globs=["**/*.py"])
    assert text.startswith("---\npaths:\n")
    assert '"**/*.py"' in text


# --- sync end to end -------------------------------------------------------
def test_write_creates_file_with_convention(isolated):
    convention.write_managed_rules([_conv("g", "prefer composition over inheritance")])
    dest = isolated / "rules" / "precept-conventions.md"
    assert dest.exists()
    assert "prefer composition over inheritance" in dest.read_text(encoding="utf-8")
    assert [p.name for p in convention.managed_files()] == ["precept-conventions.md"]


def test_write_is_idempotent(isolated):
    lessons = [_conv("g", "x"), _conv("h", "y")]
    convention.write_managed_rules(lessons)
    dest = isolated / "rules" / "precept-conventions.md"
    first = dest.read_text(encoding="utf-8")
    convention.write_managed_rules(lessons)
    assert dest.read_text(encoding="utf-8") == first  # byte-for-byte


def test_language_lesson_lands_in_path_scoped_file(isolated):
    convention.write_managed_rules(
        [_conv("l", "always add type hints", scope=Scope.LANGUAGE, scope_value="python")]
    )
    dest = isolated / "rules" / "precept-python.md"
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("---\npaths:\n")
    assert '"**/*.py"' in text and "always add type hints" in text


def test_recompile_without_lesson_removes_managed_file_only(isolated):
    # A user-authored rules file must survive; ours must be cleaned up when unbacked.
    user_rule = isolated / "rules" / "my-own.md"
    user_rule.parent.mkdir(parents=True, exist_ok=True)
    user_rule.write_text("# my own rule\n", encoding="utf-8")

    convention.write_managed_rules([_conv("g", "x")])
    assert (isolated / "rules" / "precept-conventions.md").exists()

    convention.write_managed_rules([])  # lesson archived/deleted -> recompile empties it
    assert not (isolated / "rules" / "precept-conventions.md").exists()  # ours gone
    assert user_rule.exists()  # the user's survives


def test_oversize_files_flags_large_file(isolated):
    convention.write_managed_rules([_conv(f"c{i}", f"do thing {i}") for i in range(5)])
    big = convention.oversize_files(threshold=2)
    assert big and big[0][1] > 2  # the single conventions file exceeds the tiny threshold
    assert convention.oversize_files(threshold=1000) == []  # nothing exceeds a huge threshold


def test_strip_all_is_exact_inverse(isolated):
    convention.write_managed_rules([_conv("g", "x"), _conv("l", "y", scope=Scope.LANGUAGE, scope_value="go")])
    assert convention.managed_files()
    convention.strip_all()
    assert convention.managed_files() == []
    assert not (isolated / "rules" / "precept-conventions.md").exists()
    assert not (isolated / "rules" / "precept-go.md").exists()


# --- compile_all integration ----------------------------------------------
def test_compile_all_writes_convention_without_changing_policy_count(isolated):
    # A CONVENTION lesson is SOFT: it must NOT enter the hook count compile_all returns,
    # but it MUST land as a managed rules file.
    n = compile_mod.compile_all([_conv("g", "document every public function")])
    assert n == 0  # no HARD hook policies / permission rules from a soft convention
    dest = isolated / "rules" / "precept-conventions.md"
    assert dest.exists()
    assert "document every public function" in dest.read_text(encoding="utf-8")


def test_uninstall_removes_managed_convention_files(isolated):
    compile_mod.compile_all([_conv("g", "x")])
    assert (isolated / "rules" / "precept-conventions.md").exists()
    install.uninstall_from_file()
    assert not (isolated / "rules" / "precept-conventions.md").exists()
