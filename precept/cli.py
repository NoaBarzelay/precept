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
from .models import ArtifactType, Determinism, Status

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
    # A SOFT convention lands as context in a Precept-owned rules file — name it so
    # "soft (steered)" is concrete, not vague.
    if le.artifact_type == ArtifactType.CONVENTION and not le.policies:
        from . import convention

        dest = convention.target_for(le)
        if dest is not None:
            console.print(f"  Convention written to [bold]{dest}[/bold] (loaded as context next session).")


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
def tokens(
    static: bool = typer.Option(False, "--static", help="show the fixed prompt-cost ledger (system+schema per flow) instead of the live meter"),
    refresh_baseline: bool = typer.Option(False, "--refresh-baseline", help="recompute the authoritative static ledger and overwrite token_baseline.json"),
    strict: bool = typer.Option(False, help="with --static: exit nonzero if any flow's fixed overhead drifted from the baseline (CI gate)"),
    as_json: bool = typer.Option(False, "--json", help="emit machine-readable JSON"),
) -> None:
    """Token-consumption eval for Precept's LLM flows — review where the tokens go.

    Default: aggregate the live meter (real per-flow usage from your sessions).
    --static: the FIXED prompt cost (system + schema) per flow, the part Precept
    controls, with drift vs the committed baseline."""
    import json as _json

    from .evals import tokens as tok

    if refresh_baseline:
        rows = tok.static_ledger()
        counted = [r for r in rows if r["method"] == "count_tokens"]
        if not counted:
            console.print("[red]No reachable API credentials — cannot compute an authoritative baseline.[/red]")
            console.print("[dim]count_tokens needs a metered API key; the Claude Code subscription/OAuth token does not expose it headlessly. The offline estimate still works without --refresh-baseline.[/dim]")
            raise typer.Exit(1)
        tok.write_baseline(rows)
        console.print(f"Wrote baseline for {len(counted)} flows -> {tok.BASELINE}")
        return

    if static:
        rows = tok.static_ledger()
        drifted = tok.drift(rows)
        if as_json:
            console.print(_json.dumps({"ledger": rows, "drift": drifted}, indent=2))
            if strict and drifted:
                raise typer.Exit(1)
            return
        method = "count_tokens (exact)" if all(r["method"] == "count_tokens" for r in rows) else "OFFLINE ESTIMATE (~chars/4 — no metered API key; subscription/OAuth can't run count_tokens headlessly)"
        t = Table("flow", "model", "fixed overhead (tok)", "≈$/1k calls")
        for r in rows:
            usd = "—" if r["usd_per_1k_calls"] is None else f"${r['usd_per_1k_calls']:.4f}"
            t.add_row(r["flow"], r["model"], str(r["overhead_tokens"]), usd)
        console.print(t)
        console.print(f"\n[bold]Static prompt-cost ledger[/bold] — fixed system+schema TOKENS per flow [dim]({method})[/dim]")
        console.print("[dim]Tokens are the real unit (they draw down the subscription quota); ≈$ is notional at API rates, a weight proxy.[/dim]")
        if drifted:
            console.print("[red]Drift from baseline:[/red]")
            for d in drifted:
                console.print(f"  {d['flow']}: {d['baseline']} -> {d['current']} ([red]{d['delta_pct']:+}%[/red])")
        elif tok.load_baseline():
            console.print("[green]No drift from the committed baseline.[/green]")
        else:
            console.print("[dim]No baseline committed yet — run `precept tokens --refresh-baseline` (needs an API key).[/dim]")
        if strict and drifted:
            raise typer.Exit(1)
        return

    # Default: the live meter.
    rows = tok.aggregate(tok.load_meter())
    if as_json:
        console.print(_json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(f"[dim]No usage recorded yet. The meter fills as flows run; it lives at {paths.token_usage_log()}.[/dim]")
        console.print("[dim]See the fixed per-flow cost now with `precept tokens --static`.[/dim]")
        return
    t = Table("flow", "calls", "in tok", "out tok", "in p50/p95", "out p50/p95", "≈$ notional")
    grand = 0.0
    tok_total = 0
    for r in rows:
        grand += r["cost_usd"]
        tok_total += r["in_total"] + r["out_total"]
        t.add_row(r["flow"], str(r["calls"]), str(r["in_total"]), str(r["out_total"]),
                  f"{r['in_p50']}/{r['in_p95']}", f"{r['out_p50']}/{r['out_p95']}", f"${r['cost_usd']:.4f}")
    console.print(t)
    console.print(f"\n[bold]Live token meter[/bold] — {sum(r['calls'] for r in rows)} calls, [bold]{tok_total:,} tokens[/bold] (sorted by spend)")
    console.print(f"[dim]Subscription-billed, so tokens are what count against quota; ≈${grand:.4f} is notional at API rates.[/dim]")


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

    # Managed SOFT conventions: the Precept-owned `.claude/rules/*.md` files.
    from . import convention as _convention

    conv = _convention.managed_files()
    if conv:
        console.print(f"\n[bold]Conventions[/bold] ({len(conv)} managed .claude/rules file(s)):")
        for f in conv:
            console.print(f"  [green]ok[/green]  {f}  [dim]{'present' if f.exists() else 'MISSING (recompile)'}[/dim]")
        for f, n in _convention.oversize_files():
            console.print(
                f"  [yellow]warn[/yellow]  {f} is {n} lines (> {_convention.MAX_RECOMMENDED_LINES}). "
                "Anthropic: keep a memory file lean; prefer repo/language scope or retire stale conventions."
            )

    # Inference health: are the LLM flows (DETECT/COMPILE/JUDGE) actually reachable? This
    # is the check that would have caught the silent subscription-auth failure. The probe
    # is FREE when no credentials resolve (client-side error before any call); ~1 token when
    # healthy. NOT tied to --strict: inference-unreachable is expected on a pure subscription.
    from . import inference as _inference

    ok, detail = _inference.probe()
    mark = "[green]ok[/green]" if ok else "[red]UNREACHABLE[/red]"
    console.print("\n[bold]Inference[/bold] (LLM flows: detect / compile / judge):")
    console.print(f"  {mark}  {detail}")
    if not ok:
        console.print(
            "  [dim]The flows need a metered ANTHROPIC_API_KEY (or auth_token). The Claude Code "
            "subscription exposes no credential to a subprocess, so the self-improving loop is "
            "inert without one. Deterministic enforcement of already-compiled policies still works.[/dim]"
        )
    else:
        console.print("  [dim](a healthy probe spends ~1 token)[/dim]")
    fails = _inference.last_failures()
    if fails:
        console.print("  recorded flow failures (last seen):")
        for flow, info in sorted(fails.items()):
            tag = "[red]auth/config[/red]" if info.get("auth_error") else "[yellow]transient[/yellow]"
            console.print(f"    {flow:20} {tag}  [dim]{info.get('error_type')}: {str(info.get('message'))[:80]}[/dim]")


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
def audit(
    vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)"),
    force: bool = typer.Option(False, help="run even if the daily audit already ran today"),
) -> None:
    """Daily knowledge integrity audit (slice 2): surface rename / placement / missing-
    frontmatter / missing-sources / unfiled-knowledge findings as PENDING proposals — never
    auto-applied. Throttled to once per calendar day (use --force to override)."""
    from .knowledge import ops as kops

    v = _resolve_vault_or_exit(vault)
    props = kops.run_daily(v, force=force)
    if props is None:
        last = kops.last_run_date()
        console.print(f"[dim]Already audited today (last run {last}). Use --force to re-run.[/dim]")
        return
    if not props:
        console.print("[green]No findings.[/green] Vault is clean and nothing is unfiled.")
        return
    t = Table("kind", "path", "detail")
    for p in props:
        t.add_row(p.kind, p.path[:40], p.detail[:80])
    console.print(t)
    console.print(
        f"\n[bold]{len(props)} proposal(s)[/bold] — [dim]propose only, nothing was changed. "
        "Confirm captured knowledge with `precept knowledge confirm <path>`; review renames "
        "with `precept knowledge audit`.[/dim]"
    )


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def note(title: str, body: str = typer.Option("", help="note body (or pipe via stdin)"),
         tag: list[str] = typer.Option([], help="repeatable")) -> None:
    """Capture a knowledge note (markdown source of truth + indexed for recall)."""
    from . import knowledge

    _resolve_vault_or_exit(None)  # notes now live in the vault (one knowledge store)
    text = body or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    n = knowledge.add(title, text or title, tags=list(tag))
    console.print(f"[green]Noted[/green] {n.id}" + (f" [{', '.join(n.tags)}]" if n.tags else ""))
    console.print('Recall with: [bold]precept recall "<query>"[/bold]')


@app.command()
def recall(query: str, tag: str = typer.Option(None), limit: int = typer.Option(8)) -> None:
    """Recall knowledge notes by keyword (BM25), optionally filtered by tag."""
    from . import knowledge

    _resolve_vault_or_exit(None)  # recall reads the vault-backed index
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
    """Rebuild the vault-backed knowledge index from the markdown (proves it's derived)."""
    from . import knowledge
    from .knowledge import config as kconfig

    _resolve_vault_or_exit(None)
    n = knowledge.reindex()
    console.print(f"Rebuilt the knowledge index from the vault markdown: "
                  f"{n} docs -> {kconfig.knowledge_index_db()}")


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


@knowledge_app.command("confirm")
def knowledge_confirm(
    path: str,
    vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)"),
) -> None:
    """Confirm a PENDING captured knowledge file (strip its `precept_status: pending`),
    promoting it to a final knowledge file. `path` is vault-relative or absolute."""
    from .knowledge import store

    v = _resolve_vault_or_exit(vault)
    target = (v / path) if not str(path).startswith("/") else __import__("pathlib").Path(path)
    if not target.exists():
        console.print(f"[red]No such file: {target}[/red]")
        raise typer.Exit(1)
    if not store.is_pending(target):
        console.print(f"[dim]{target.name} is already confirmed (not pending).[/dim]")
        return
    store.confirm(target)
    console.print(f"[green]Confirmed[/green] {target.relative_to(v).as_posix()} (now final).")


@knowledge_app.command("capture")
def knowledge_capture(
    title: str,
    body: str = typer.Option(..., help="the durable knowledge body"),
    vault: str = typer.Option(None, help="vault root (else $PRECEPT_VAULT)"),
    tag: list[str] = typer.Option([], help="repeatable"),
) -> None:
    """Manually file a PENDING knowledge file (auto-routed to the best folder). Same path
    the per-turn capture uses; useful for testing routing."""
    from .knowledge import store

    _resolve_vault_or_exit(vault)
    res = store.file_knowledge(title, body, tags=list(tag) or None, pending=True)
    route = (f"routed -> {res.folder} (conf {res.confidence:.2f})"
             if res.routed else f"new/default folder -> {res.folder}")
    console.print(f"[green]Captured PENDING[/green] {res.rel}  [dim]({route})[/dim]")
    console.print(f"Confirm with: [bold]precept knowledge confirm \"{res.rel}\"[/bold]")


if __name__ == "__main__":  # pragma: no cover
    app()
