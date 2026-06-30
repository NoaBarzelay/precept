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
    console.print("  PreToolUse, Stop, SessionEnd are now wired. Restart any open Claude Code session.")


@app.command()
def uninstall() -> None:
    """Remove Precept's hooks from ~/.claude/settings.json (leaves other settings intact)."""
    from . import install as _install

    p = _install.uninstall_from_file()
    console.print(f"[yellow]Uninstalled[/yellow] Precept hooks from {p}.")


# ---------------------------------------------------------------------------
# `precept knowledge ...` — the vault knowledge pillar (index / search / audit).
# Operates on a CONFIGURABLE vault (PRECEPT_VAULT or --vault); the derived index
# lives on local disk, never in the vault.
# ---------------------------------------------------------------------------
knowledge_app = typer.Typer(add_completion=False, help="Knowledge pillar over your markdown vault.")
app.add_typer(knowledge_app, name="knowledge")


def _resolve_vault_or_exit(vault: str | None):
    from .knowledge import config as kconfig

    try:
        return kconfig.resolve_vault(vault)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@knowledge_app.command("index")
def knowledge_index(vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)")) -> None:
    """(Re)build the knowledge index from the vault markdown (derived, local-only)."""
    from .knowledge import config as kconfig, index as kindex

    v = _resolve_vault_or_exit(vault)
    db = kconfig.knowledge_index_db()
    n = kindex.build(v, db)
    console.print(f"Indexed {n} markdown docs from {v} -> {db}")


@knowledge_app.command("search")
def knowledge_search(
    query: str,
    vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)"),
    k: int = typer.Option(10, help="max results"),
) -> None:
    """Search the knowledge index (FTS5 BM25)."""
    from .knowledge import config as kconfig, index as kindex

    _resolve_vault_or_exit(vault)
    hits = kindex.search(kconfig.knowledge_index_db(), query, k=k)
    if not hits:
        console.print("[dim]No matches (build the index first: precept knowledge index).[/dim]")
        return
    t = Table("score", "title", "folder", "type", "path")
    for h in hits:
        t.add_row(f"{h['score']:.2f}", h["title"][:48], h["folder"][:28],
                  h["type"] or "-", h["path"])
    console.print(t)


@knowledge_app.command("audit")
def knowledge_audit(vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)")) -> None:
    """Print the integrity/rename plan (DRY-RUN — never applies anything)."""
    from .knowledge import audit as kaudit, conventions as kconv

    v = _resolve_vault_or_exit(vault)
    spec, stats = kconv.suggest_from_vault(v)
    findings = kaudit.audit(v, spec)
    if not findings:
        console.print("[green]No findings.[/green] Vault is clean under the derived spec.")
        return
    renames = [f for f in findings if f.kind == kaudit.FindingKind.RENAME]
    if renames:
        t = Table("path", "reasons", "proposed", "inbound", "collision", "type")
        for f in renames:
            t.add_row(
                f.path,
                ",".join(r.value for r in f.reasons),
                f.proposed_stem or "[TODO: AI translate]",
                str(f.inbound_link_refs),
                "yes" if f.collision else "",
                f.doc_type or "-",
            )
        console.print(t)
    for f in findings:
        if f.kind != kaudit.FindingKind.RENAME:
            console.print(f"[yellow]{f.kind.value}[/yellow]  {f.path}  [dim]{f.detail}[/dim]")
    console.print(
        f"\n[bold]{len(findings)} findings[/bold] "
        f"(scanned {stats.total} docs, {stats.non_exempt} non-exempt). "
        "[dim]Dry-run only — nothing was changed.[/dim]"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
