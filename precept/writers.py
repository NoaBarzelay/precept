"""Writer registry: the COMMIT seam between the catalog and its artifact hosts.

Every entity type rides the same spine (DETECT -> COMPILE -> REVIEW) and differs
only in its COMMIT target: the host artifact its kept lessons are written into.
This module names that seam. A `Writer` wraps one commit target behind a uniform
contract; the `WRITERS` registry maps each target that exists today to its writer,
and `compile_all`, `precept keep`, and `precept doctor` iterate the registry
instead of hardcoding hosts.

The Writer contract (every implementation must honor all of it):

- **Sidecar manifest.** The set of things a writer manages is recorded in a
  manifest in the local state dir (never in the host artifact itself), so a
  re-sync or strip removes ONLY what Precept wrote, never user-authored content.
- **Idempotent full-sync.** `sync(lessons)` regenerates the writer's artifacts as
  a pure function of the ACTIVE lessons: re-running it on the same catalog is
  byte-for-byte stable, and an artifact whose backing lessons are gone is removed.
- **Atomic writes.** Every write goes through `safety.atomic_write_text` (temp
  file in the same directory, fsync, `os.replace`), with a `.bak` where the file
  pre-exists and is shared with the user (settings.json).
- **Exact-inverse strip.** `strip_all()` removes exactly the manifest-recorded
  managed content and resets the manifest; user-authored content is untouched.
- **Never touch user-authored content.** A writer either owns a whole generated
  file (conventions) or a marker-managed subset of entries inside a shared file
  (permissions); it never edits the user's own lines.

Writers here are thin adapters: the real logic stays in the host module
(`convention.py`, `install.py`); the adapter only presents the shared interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import convention, install
from .models import ArtifactType, Lesson


class Writer(Protocol):
    """The commit-target contract (see the module docstring for the invariants)."""

    # How `precept doctor` labels this writer's section when it owns files.
    doctor_title: str
    doctor_detail: str

    def sync(self, lessons: list[Lesson]) -> None:
        """Idempotent full-sync of this writer's managed artifacts from the ACTIVE
        lessons (the whole catalog is passed; the writer selects what it owns)."""
        ...

    def strip_all(self) -> None:
        """Exact-inverse removal of everything this writer manages (uninstall)."""
        ...

    def managed_files(self) -> list[Path]:
        """The files this writer owns OUTRIGHT, for `precept doctor`. A writer that
        manages entries inside a user-shared file (not whole files) returns []."""
        ...

    def destination_for(self, lesson: Lesson) -> Path | None:
        """Where a kept soft lesson's artifact lands, for user-facing messaging in
        `precept keep`; None when unplaceable or not applicable to this writer."""
        ...


class ConventionWriter:
    """CONVENTION -> Precept-owned `.claude/rules/*.md` files (host: convention.py)."""

    doctor_title = "Conventions"
    doctor_detail = "managed .claude/rules file(s)"

    def sync(self, lessons: list[Lesson]) -> None:
        convention.write_managed_rules(lessons)

    def strip_all(self) -> None:
        convention.strip_all()

    def managed_files(self) -> list[Path]:
        return convention.managed_files()

    def destination_for(self, lesson: Lesson) -> Path | None:
        return convention.target_for(lesson)


class PermissionsWriter:
    """Permission-rule strings -> the marker-managed deny/ask block in Claude Code's
    settings.json (host: install.py).

    Deliberately NOT keyed by an ArtifactType: a permission entry is produced by any
    lesson whose policy carries a `permission_rule` (typically a RULE whose clean
    tool+path ban routes to native enforcement), not by a dedicated entity kind, so
    the registry keys this writer by the literal string "permissions" rather than
    forcing a fake enum member.
    """

    doctor_title = "Permissions"
    doctor_detail = "managed settings.json permission entr(ies)"

    def sync(self, lessons: list[Lesson]) -> None:
        # Lazy import: compile.py imports this module at the top level; the rule
        # aggregation (which lessons yield which permission strings) is compile
        # logic and stays there.
        from . import compile as _compile

        install.write_managed_permissions(_compile.aggregate_permission_rules(lessons))

    def strip_all(self) -> None:
        # Syncing an empty rule set drops exactly the manifest-recorded strings and
        # resets the manifest: the exact inverse of any prior sync.
        install.write_managed_permissions({"deny": [], "ask": []})

    def managed_files(self) -> list[Path]:
        # settings.json is user-owned; this writer manages STRINGS inside it, never
        # a whole file, so it reports no owned files (doctor lists conventions only,
        # exactly as before the registry existed).
        return []

    def destination_for(self, lesson: Lesson) -> Path | None:
        # A permission lesson always carries a HARD policy, so `keep`'s soft
        # "written to" message never applies to this writer.
        return None


# ---------------------------------------------------------------------------
# The registry. HOW A NEW ENTITY TYPE LANDS (the point of this seam): write one
# writer module wrapping its commit target (sidecar manifest, idempotent sync,
# atomic writes, exact-inverse strip; see the module docstring), add a thin
# adapter class above, and add ONE line here keyed by the entity's ArtifactType
# value. `compile_all` (sync on every recompile), `precept keep` (naming the
# landing file), and `precept doctor` (listing owned files) all pick it up with
# no further wiring. Keys are the ArtifactType `.value` strings when the target
# maps to one entity kind, or a plain string ("permissions") when it does not.
# Insertion order is sync order: permissions before conventions, matching the
# pre-registry call order in compile_all.
# ---------------------------------------------------------------------------
WRITERS: dict[str, Writer] = {
    "permissions": PermissionsWriter(),
    ArtifactType.CONVENTION.value: ConventionWriter(),
}


def for_artifact(artifact_type: ArtifactType) -> Writer | None:
    """The writer whose commit target belongs to this artifact type, or None when
    the type has no commit target yet (or, like permissions, is not type-keyed)."""
    return WRITERS.get(artifact_type.value)
