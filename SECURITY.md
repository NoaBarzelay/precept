# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repo's Security tab) rather than a public issue.
Include repro steps and the affected version/commit. You will get an acknowledgement
within a few days.

## What Precept installs and touches

Precept is a local developer tool. It runs entirely on your machine and adds nothing
to any remote service of its own. Concretely, `precept install` will:

- **Register five Claude Code hooks** in `~/.claude/settings.json`: `PreToolUse` (all
  tools), `Stop`, `UserPromptSubmit`, `SessionStart`, and `SessionEnd`. Each points at a
  `precept-hook-*` command in Precept's own install. `settings.json` is backed up before
  every edit, and `precept uninstall` removes exactly these entries (atomic, reversible).
- **Read and write local state only:**
  - `~/.precept/` — the catalog of rule cards (plain markdown) plus config.
  - `~/.local/state/precept/` (or `$XDG_STATE_HOME`) — the compiled policy cache, ledgers,
    and per-session cursors. Never the synced vault; nothing here leaves the machine.
- **Optionally write `.claude/rules/*.md`** in a project for SOFT convention artifacts.
  These are removed on uninstall.

## What runs, and what leaves your machine

- The hooks are deterministic checks over local data. They **block or inject text**; they
  do not exfiltrate anything.
- The learning loop (**DETECT** at `SessionEnd`, and the **judge** for judgment-gated
  rules) makes model calls. On the default subscription backend (`PRECEPT_INFERENCE=cli`)
  these run through your local `claude` CLI; with an API key they call the Anthropic API.
  In both cases **transcript excerpts and prompt text are sent to the model** for
  classification, exactly as any Claude Code turn does. Set `PRECEPT_DISABLE_DETECT=1`
  to turn the learning loop off entirely and keep Precept in enforcement-only mode.
- Nested-inference recursion is guarded by the `PRECEPT_SUBPROCESS` sentinel so a hook
  can never fork-bomb the machine by re-triggering itself.

## Trust boundary

Precept enforces rules **you** keep. Rules are drafted from your own corrections, shown
to you for review (`precept list` / `precept keep` / `precept delete`), and stored as
readable, version-controllable markdown. Nothing is auto-enforced without landing in the
catalog you can inspect.
