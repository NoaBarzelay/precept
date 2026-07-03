"""Writer registry (the COMMIT seam): the registry holds exactly today's commit
targets, `compile_all` through the registry produces byte-identical artifacts to
the direct convention/install calls it replaced (golden), strip via the registry
is still an exact inverse, and doctor sees the same managed files as before.
All isolated to temp $PRECEPT_CLAUDE_HOME / $PRECEPT_STATE_DIR."""

import json
from datetime import date

import pytest

from precept import compile as compile_mod
from precept import convention, install, paths, writers
from precept.models import (
    ArtifactType, CheckKind, Condition, Decision, Determinism, EnforcementTier,
    HookEvent, Lesson, Match, MatchOp, Origin, Policy, Scope, Status,
)
from precept.safety import atomic_write_text


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    home.mkdir()
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(home))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    return home


def _conv(lid: str, do: str, *, scope=Scope.GLOBAL, scope_value=None) -> Lesson:
    le = Lesson(
        id=lid, created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        artifact_type=ArtifactType.CONVENTION, determinism=Determinism.STYLISTIC,
        scope=scope, scope_value=scope_value, trigger="t", what_was_wrong="w",
        what_to_do_instead=do,
    )
    le.status = Status.ACTIVE
    return le


def _perm_lesson(lid: str, rule: str) -> Lesson:
    le = Lesson(
        id=lid, created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        determinism=Determinism.DETERMINISTIC, trigger="t", what_was_wrong="w",
        what_to_do_instead="d",
    )
    le.status = Status.ACTIVE
    le.policies = [Policy(
        id=f"{lid}-p1", lesson_id=lid, enforcement_tier=EnforcementTier.HARD,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.DENY, message="blocked", permission_rule=rule,
        match=Match(tool="Read", conditions=[
            Condition(field="file_path", op=MatchOp.GLOB, value=".env"),
        ]),
    )]
    return le


def _lessons() -> list[Lesson]:
    return [
        _conv("conv-global", "prefer composition over inheritance"),
        _conv("conv-py", "use type hints", scope=Scope.LANGUAGE, scope_value="python"),
        _perm_lesson("L-perm", "Read(.env)"),
    ]


# --- registry shape ----------------------------------------------------------
def test_registry_contains_expected_writers():
    assert list(writers.WRITERS.keys()) == ["permissions", "convention"]
    assert isinstance(writers.WRITERS["permissions"], writers.PermissionsWriter)
    assert isinstance(writers.WRITERS["convention"], writers.ConventionWriter)
    # the type-keyed lookup used by `precept keep`
    assert writers.for_artifact(ArtifactType.CONVENTION) is writers.WRITERS["convention"]
    assert writers.for_artifact(ArtifactType.RULE) is None  # rules commit to the hook cache


def test_destination_for_matches_convention_target(isolated):
    le = _conv("g", "x")
    w = writers.for_artifact(le.artifact_type)
    assert w is not None
    assert w.destination_for(le) == convention.target_for(le)
    assert writers.WRITERS["permissions"].destination_for(le) is None


# --- golden: registry path == pre-registry direct calls ----------------------
def _direct_compile(lessons: list[Lesson]) -> int:
    """The exact pre-registry body of compile_all (commit 6f1932b): direct calls to
    install.write_managed_permissions and convention.write_managed_rules."""
    compiled: list[dict] = []
    perm_rules: dict[str, list[str]] = {"deny": [], "ask": []}
    for lesson in lessons:
        compiled.extend(compile_mod._runtime_policies(lesson))
        lr = compile_mod._permission_rules(lesson)
        perm_rules["deny"].extend(lr["deny"])
        perm_rules["ask"].extend(lr["ask"])
    paths.ensure_dirs()
    atomic_write_text(paths.policies_cache(), json.dumps(compiled, indent=2))
    perm_rules = {b: sorted(set(v)) for b, v in perm_rules.items()}
    install.write_managed_permissions(perm_rules)
    convention.write_managed_rules(lessons)
    return len(compiled) + sum(len(v) for v in perm_rules.values())


def _artifacts(home) -> dict[str, str]:
    """Every artifact either path writes, with the per-run temp prefix normalized so
    two isolated runs are byte-comparable (manifests store absolute paths)."""
    out = {}
    for name, p in {
        "settings": home / "settings.json",
        "rules-global": home / "rules" / "precept-conventions.md",
        "rules-python": home / "rules" / "precept-python.md",
        "cache": paths.policies_cache(),
        "perm-manifest": paths.managed_permissions_manifest(),
        "conv-manifest": paths.managed_conventions_manifest(),
    }.items():
        out[name] = p.read_text(encoding="utf-8").replace(str(home.parent), "<RUN>")
    return out


def test_compile_all_via_registry_is_byte_identical_to_direct_calls(tmp_path, monkeypatch):
    runs = {}
    counts = {}
    for tag, fn in (("direct", _direct_compile), ("registry", compile_mod.compile_all)):
        home = tmp_path / tag / "claude"
        home.mkdir(parents=True)
        monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(home))
        monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / tag / "state"))
        counts[tag] = fn(_lessons())
        runs[tag] = _artifacts(home)
    assert runs["registry"] == runs["direct"]  # byte-identical, artifact by artifact
    assert counts["registry"] == counts["direct"] == 1  # 0 hook policies + 1 perm rule


# --- strip via registry is still an exact inverse -----------------------------
def test_registry_strip_is_exact_inverse(isolated):
    base = {"model": "x", "permissions": {"deny": ["Bash(sudo *)"]}}
    install.settings_path().write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    compile_mod.compile_all(_lessons())
    assert convention.managed_files()  # conventions landed
    assert "Read(.env)" in json.loads(
        install.settings_path().read_text(encoding="utf-8"))["permissions"]["deny"]

    for w in writers.WRITERS.values():
        w.strip_all()

    # conventions: files gone, manifest empty
    assert convention.managed_files() == []
    assert not (isolated / "rules").exists()  # empty rules dir we created is pruned
    # permissions: only ours removed; the user's settings restored exactly
    assert json.loads(install.settings_path().read_text(encoding="utf-8")) == base


def test_registry_sync_is_idempotent(isolated):
    compile_mod.compile_all(_lessons())
    first = _artifacts(isolated)
    compile_mod.compile_all(_lessons())
    assert _artifacts(isolated) == first  # byte-for-byte stable re-sync


# --- doctor still reports the same managed files ------------------------------
def test_doctor_sees_same_managed_files_as_before(isolated):
    compile_mod.compile_all(_lessons())
    # what the registry-driven doctor iterates == what the old convention-only doctor saw
    reported = [f for w in writers.WRITERS.values() for f in w.managed_files()]
    assert reported == convention.managed_files()
    assert sorted(f.name for f in reported) == ["precept-conventions.md", "precept-python.md"]
    # the permissions writer owns strings inside settings.json, never whole files
    assert writers.WRITERS["permissions"].managed_files() == []
