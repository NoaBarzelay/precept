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
    le.needs_review = False  # item 3: the user has now answered the proactive prompt
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
        le.needs_review = False  # item 3: answered (vetoed)
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
def detect(
    transcript: str,
    session_id: str = typer.Option(None, "--session-id", help="session id (keys the per-session cursor + lock)"),
    cwd: str = typer.Option(None, "--cwd", help="session working dir (lets a repo-scoped lesson resolve its root)"),
) -> None:
    """Classify a session transcript; mint any correction as a PENDING lesson.

    Incremental: only the NEW turns since this session's cursor are classified, gated by a
    cheap regex pre-filter and a per-session lock (item 1)."""
    from . import detect as _detect

    minted = _detect.detect_from_transcript(
        transcript, session=transcript, session_id=session_id, cwd=cwd
    )
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
def evals(strict: bool = typer.Option(False, help="exit nonzero on any miss/false-block (CI gate)")) -> None:
    """Run the Tier-1 deterministic enforcement eval over the committed golden set."""
    from .evals import harness

    rep, rows = harness.run_golden()
    t = Table("case", "expect", "blocked", "outcome")
    for r in rows:
        t.add_row(r["id"], r["expect"], "yes" if r["blocked"] else "no", r["outcome"])
    console.print(t)
    clean = rep.recall == 1.0 and rep.false_block_rate == 0.0
    console.print(f"\n[bold]Tier-1 enforcement eval[/bold] — {rep.n} committed cases (deterministic, zero variance):")
    console.print(f"  recall (violations caught):   {rep.recall:.0%}  [dim](TP={rep.tp} FN={rep.fn})[/dim]")
    console.print(f"  false-block rate (compliant): {rep.false_block_rate:.0%}  [dim](FP={rep.fp} TN={rep.tn})[/dim]")
    console.print(f"  precision: {rep.precision:.0%}   accuracy: {rep.accuracy:.0%}")
    msg = "100% of violations blocked, 0 false-blocks on the deterministic subset."
    console.print(f"  [green]{msg}[/green]" if clean else "  [red]Regression — see outcomes above.[/red]")
    if strict and not clean:
        raise typer.Exit(1)


@app.command()
def doctor(strict: bool = typer.Option(False, help="exit nonzero if any hook is unreachable (CI gate)")) -> None:
    """Print resolved paths + environment, check the iCloud-safety invariant, and verify
    each installed hook command actually resolves (item 2)."""
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

    # --- BEGIN item 2: hook-reachability checks (additive; safe to relocate) ----------
    from . import doctor as _doctor

    checks = _doctor.check_hooks()
    console.print("\n[bold]Hooks[/bold] (settings.json -> reachable entrypoint):")
    for c in checks:
        mark = "[green]ok[/green]" if c.ok else "[red]FAIL[/red]"
        target = c.command if c.command is not None else "(not installed)"
        console.print(f"  {mark}  {c.event:16} {target}  [dim]{c.detail}[/dim]")
    if _doctor.all_ok(checks):
        console.print("  [green]all hooks reachable.[/green]")
    else:
        console.print("  [red]Some hooks are not reachable. Run `precept install` (it writes absolute paths).[/red]")
        if strict:
            raise typer.Exit(1)
    # --- END item 2 -------------------------------------------------------------------


@app.command()
def govern(
    decay_days: int = typer.Option(30, help="propose retiring an active rule that never fired in this many days"),
    conflicts: bool = typer.Option(False, help="also run LLM conflict-detection over active rules"),
    apply_decay: str = typer.Option(None, "--apply-decay", help="archive this rule id (decay)"),
    supersede: tuple[str, str] = typer.Option((None, None), "--supersede", help="OLD NEW: archive OLD, point it at NEW"),
) -> None:
    """Rule governance (item 6): surface decay/supersede/conflict PROPOSALS — never
    auto-applied. Use --apply-decay / --supersede to act on one (then it recompiles)."""
    from . import governance

    if apply_decay:
        le = governance.apply_decay(apply_decay)
        n = _compile.compile_all()
        console.print(f"[yellow]Archived[/yellow] {le.id} (decayed). Recompiled {n} active policies.")
        return
    if supersede and supersede[0] and supersede[1]:
        old, new = governance.apply_supersede(supersede[0], supersede[1])
        n = _compile.compile_all()
        console.print(f"[yellow]Archived[/yellow] {old.id} -> superseded by {new.id}. Recompiled {n}.")
        return

    decay = governance.propose_decay(threshold_days=decay_days)
    if decay:
        console.print("[bold]Decay proposals[/bold] (active, never fired):")
        for d in decay:
            console.print(f"  {d.lesson_id}  [dim]{d.reason}[/dim]  -> precept govern --apply-decay {d.lesson_id}")
    else:
        console.print("[dim]No decay proposals.[/dim]")
    if conflicts:
        for c in governance.detect_conflicts():
            console.print(f"[red]Conflict[/red] {c.lesson_a} <-> {c.lesson_b}: {c.reason}")


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def note(title: str, body: str = typer.Option("", help="note body (or pipe via stdin)"),
         tag: list[str] = typer.Option([], help="repeatable")) -> None:
    """Capture a knowledge note (markdown source of truth + indexed for recall)."""
    from . import knowledge

    text = body or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    n = knowledge.add(title, text or title, tags=list(tag))
    console.print(f"[green]Noted[/green] {n.id}" + (f" [{', '.join(n.tags)}]" if n.tags else ""))
    console.print('Recall with: [bold]precept recall "<query>"[/bold]')


@app.command()
def recall(query: str, tag: str = typer.Option(None), limit: int = typer.Option(8)) -> None:
    """Recall knowledge notes by keyword (BM25), optionally filtered by tag."""
    from . import knowledge

    hits = knowledge.search(query, limit=limit, tag=tag)
    if not hits:
        console.print("[dim]No matching notes.[/dim]")
        return
    for n in hits:
        meta = f"{n.id}" + (f" · {', '.join(n.tags)}" if n.tags else "")
        console.print(f"[bold]{n.title}[/bold]  [dim]{meta}[/dim]")
        console.print(f"  {n.body[:180]}")


@app.command()
def reindex() -> None:
    """Rebuild the knowledge index from the markdown notes (proves it's derived)."""
    from . import knowledge

    n = knowledge.reindex()
    console.print(f"Rebuilt the knowledge index from markdown: {n} notes -> {paths.index_db()}")


@app.command()
def install() -> None:
    """Register Precept's hooks in ~/.claude/settings.json (idempotent, atomic, backed up)."""
    from . import install as _install

    p = _install.install_to_file()
    console.print(f"[green]Installed[/green] Precept hooks -> {p} (backup at {p.name}.bak)")
    console.print("  PreToolUse, Stop, UserPromptSubmit, SessionStart, SessionEnd are now wired. "
                  "Restart any open Claude Code session.")


@app.command()
def uninstall() -> None:
    """Remove Precept's hooks from ~/.claude/settings.json (leaves other settings intact)."""
    from . import install as _install

    p = _install.uninstall_from_file()
    console.print(f"[yellow]Uninstalled[/yellow] Precept hooks from {p}.")


if __name__ == "__main__":  # pragma: no cover
    app()
