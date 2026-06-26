"""`precept` — the catalog CLI and the human review gate.

The pending -> active gate (`keep`/`delete`) is the credibility core: nothing
enforces until a human keeps it.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, catalog, compile as _compile, paths
from .models import Determinism, Status

app = typer.Typer(add_completion=False, help="Policy-as-code for your coding agent.")
console = Console()


def _find(lesson_id: str):
    for lesson in catalog.load_all():
        if lesson.id == lesson_id:
            return lesson
    console.print(f"[red]No lesson with id '{lesson_id}'.[/red]")
    raise typer.Exit(1)


@app.command("list")
def list_() -> None:
    """List all lessons in the catalog."""
    lessons = catalog.load_all()
    if not lessons:
        console.print("[dim]Catalog is empty. Lessons are minted from corrections (precept detect) "
                      "or imported (precept bootstrap).[/dim]")
        return
    t = Table("id", "status", "tier", "kind", "conf", "trigger")
    for le in lessons:
        tier = le.policies[0].enforcement_tier.value if le.policies else "-"
        kind = le.determinism.value
        t.add_row(le.id, le.status.value, tier, kind, f"{le.confidence:.2f}", le.trigger[:48])
    console.print(t)


@app.command()
def show(lesson_id: str) -> None:
    """Show a lesson's full card."""
    console.print(catalog.render(_find(lesson_id)))


@app.command()
def why(lesson_id: str) -> None:
    """Show a lesson's provenance (where it came from and why it's trusted)."""
    le = _find(lesson_id)
    console.print(f"[bold]{le.id}[/bold]  ({le.status.value}, confidence {le.confidence:.2f})")
    console.print(f"  origin:   {le.origin.value} (session {le.source_session})")
    console.print(f"  created:  {le.created}")
    console.print(f"  quote:    {le.origin_quote or '[dim](none)[/dim]'}")
    s = le.signals
    console.print(f"  signals:  quote={s.has_verbatim_quote} imperative={s.imperative_correction} "
                  f"deterministic={s.deterministic_by_construction} kept={s.human_kept} fired={s.fire_count}")
    console.print(f"  policies: {len(le.policies)}")


@app.command()
def keep(lesson_id: str) -> None:
    """Keep a pending lesson -> ACTIVE. Deterministic ones are compiled into an
    enforcing policy (matcher synthesis); the rest stay soft."""
    le = _find(lesson_id)
    le.status = Status.ACTIVE
    le.signals.human_kept = True
    if not le.policies and le.determinism != Determinism.STYLISTIC:
        from . import synthesize  # lazy: only the keep path needs the SDK

        try:
            synthesize.compile_lesson(le)
        except Exception:
            pass  # fail closed: kept as soft, no junk policy
    catalog.write(le)
    n = _compile.compile_all()
    tier = "HARD (enforced)" if le.policies else "soft (steered)"
    console.print(f"[green]Kept[/green] {le.id} -> {tier}. Recompiled {n} active policies.")


@app.command()
def synthesize(lesson_id: str) -> None:
    """(Re)compile a lesson into an enforcing policy via matcher synthesis."""
    from . import synthesize as _syn

    le = _find(lesson_id)
    le.policies = []
    _syn.compile_lesson(le)
    catalog.write(le)
    n = _compile.compile_all()
    if le.policies:
        console.print(f"[green]Synthesized[/green] a HARD policy for {le.id}. Recompiled {n}.")
    else:
        console.print(f"[yellow]Could not compile[/yellow] {le.id} to a hard rule — kept soft.")


@app.command()
def delete(lesson_id: str, hard: bool = typer.Option(False, help="remove the card file instead of archiving")) -> None:
    """Veto a lesson -> ARCHIVED (or removed with --hard)."""
    le = _find(lesson_id)
    if hard:
        catalog.card_path(le.id).unlink(missing_ok=True)
    else:
        le.status = Status.ARCHIVED
        le.signals.human_kept = False
        catalog.write(le)
    n = _compile.compile_all()
    console.print(f"[yellow]{'Removed' if hard else 'Archived'}[/yellow] {le.id}. Recompiled {n} active policies.")


@app.command()
def bootstrap() -> None:
    """Import your existing ~/.claude setup (permission rules + CLAUDE.md) as PENDING lessons."""
    from . import bootstrap as _bootstrap

    minted = _bootstrap.bootstrap()
    if not minted:
        console.print("[dim]Nothing new to import (no ~/.claude rules found, or already imported).[/dim]")
        return
    hard = sum(1 for le in minted if le.policies)
    console.print(
        f"[green]Imported[/green] {len(minted)} pending lessons "
        f"({hard} ready-to-enforce from permission rules, {len(minted) - hard} soft from CLAUDE.md)."
    )
    console.print("Review: [bold]precept list[/bold] · keep: [bold]precept keep <id>[/bold]")


@app.command()
def detect(transcript: str) -> None:
    """Classify a session transcript; mint any correction as a PENDING lesson."""
    from . import detect as _detect

    minted = _detect.detect_from_transcript(transcript, session=transcript)
    if not minted:
        console.print("[dim]No new correction detected (or already in catalog).[/dim]")
        return
    for le in minted:
        console.print(f"[green]Minted PENDING[/green] {le.id}: {le.trigger}")
    console.print("Review: [bold]precept why <id>[/bold] · keep: [bold]precept keep <id>[/bold]")


@app.command("compile")
def compile_cmd() -> None:
    """Recompile the enforcement cache from the catalog."""
    n = _compile.compile_all()
    console.print(f"Compiled {n} active HARD policies -> {paths.policies_cache()}")


@app.command()
def doctor() -> None:
    """Print resolved paths + environment (and check the iCloud-safety invariant)."""
    console.print(f"precept {__version__}  (python {sys.version.split()[0]})")
    console.print(f"  catalog (source of truth): {paths.catalog_dir()}")
    console.print(f"  state/index (local-only):  {paths.state_dir()}")
    console.print(f"  policy cache:              {paths.policies_cache()}")
    console.print(f"  claude home (commit tgt):  {paths.claude_home()}")
    synced = any(tok in str(paths.state_dir()) for tok in ("Mobile Documents", "iCloud", "Dropbox"))
    if synced:
        console.print("  [red]WARNING: state dir looks cloud-synced — SQLite can corrupt. Set PRECEPT_STATE_DIR to a local path.[/red]")
    else:
        console.print("  [green]state dir is on a local path (safe for SQLite).[/green]")


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def reindex() -> None:
    """Rebuild the knowledge index from markdown notes. [P2 — not yet implemented]"""
    console.print("[dim]reindex: knowledge index lands in P2 (FTS5 first, sqlite-vec if a recall eval demands it).[/dim]")


@app.command()
def install() -> None:
    """Register Precept's hooks in ~/.claude/settings.json (idempotent, atomic, backed up)."""
    from . import install as _install

    p = _install.install_to_file()
    console.print(f"[green]Installed[/green] Precept hooks -> {p} (backup at {p.name}.bak)")
    console.print("  PreToolUse, Stop, SessionEnd are now wired. Restart any open Claude Code session.")


@app.command()
def uninstall() -> None:
    """Remove Precept's hooks from ~/.claude/settings.json (leaves other settings intact)."""
    from . import install as _install

    p = _install.uninstall_from_file()
    console.print(f"[yellow]Uninstalled[/yellow] Precept hooks from {p}.")


if __name__ == "__main__":  # pragma: no cover
    app()
