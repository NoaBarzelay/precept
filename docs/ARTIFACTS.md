# The 9 artifact types

Precept's vocabulary. A *process* or *entity* Precept learns is captured as one of
these artifacts: each has a Precept-side representation (markdown card, the source of
truth) and compiles to a concrete Claude Code target. Every artifact is labeled
**HARD** (Claude Code actually enforces it) or **SOFT** (it steers behavior, with no
guarantee of compliance). Precept only claims enforcement for the HARD tier.

| # | Type | Pillar | Tier | Claude Code target | Built |
|---|------|--------|------|--------------------|-------|
| 1 | Rule | process | HARD | hooks (PreToolUse/Stop/UserPromptSubmit) + permission deny | ✅ |
| 2 | Knowledge note | entity/data | SOFT (recall) | Precept-native (FTS index, injected/recalled) | ✅ |
| 3 | CLAUDE.md edit | process | SOFT | `~/.claude/CLAUDE.md` / `.claude/rules/*.md` | ⬜ |
| 4 | Skill | process | SOFT | `.claude/skills/<n>/SKILL.md` | ⬜ |
| 5 | Agent persona | process | HARD (tools) + SOFT (prompt) | `.claude/agents/<n>.md` | ⬜ |
| 6 | Output style | process | SOFT | `.claude/output-styles/<n>.md` | ⬜ |
| 7 | Slash command | process | SOFT | `.claude/skills/` or `.claude/commands/` | ⬜ |
| 8 | MCP / tool config | process | config | `.mcp.json` / `mcpServers` | ⬜ |
| 9 | Permission profile | process | HARD | `settings.json` `permissions` | 🟡 import + clean-ban write-back |

---

## 1. Rule  (HARD, built)

**What.** A deterministic or judgment guardrail on agent behavior: the enforceable
subset of a process. Flavors: single-call ("never `npm`, use `pnpm`" — deny or a clean
`rewrite` to the corrected value), trajectory ("tests must run before claiming success"),
judgment ("don't leave stub code", a model verdict at a deterministic gate), and
prompt-time ("always include the ticket id", over the user's own prompt). Rules are
scope-aware: GLOBAL by default, or REPO (fires only when cwd is inside the repo root).

**When/how used.** Fires automatically: single-call at a tool call (PreToolUse),
trajectory and judgment at turn-end (Stop), prompt rules at prompt submission
(UserPromptSubmit). The user never invokes it; the hook does.

**Structure.** Precept `Lesson` holding 1..N `Policy{hook_event, check_kind,
decision ∈ {allow,deny,ask,rewrite}, match | trajectory | judgment_prompt, message,
enforcement_tier}`. Compiles to a `settings.json` hook entry that calls
`precept-hook-pretooluse` / `-stop`, which reads the compiled `policies.json`. Clean
tool+path bans can instead target a `permissions.deny` rule (see #9).

**Infra.** Card in `~/.precept/catalog/*.md` (source of truth) -> `policies.json`
(local cache) -> our hooks. HARD via PreToolUse `permissionDecision: deny` / Stop
`{decision: block}`. This is the most-built capability (single-call + trajectory +
judgment all work, 100%-recall eval).

## 2. Knowledge note  (SOFT recall, built)

**What.** A fact / entity / datum you recall later ("what do I know about X"). The
entity-and-data pillar. Today it is freeform notes; the planned upgrade is a *typed*
entity catalog (projects, domains, people, tools as first-class records).

**When/how used.** Captured by `precept note`, by `precept knowledge capture`, or
AUTO-CAPTURED from a session (the per-turn detect pass mines durable knowledge worth
filing, writes it auto-routed + PENDING); recalled by `precept recall` (keyword/BM25 +
tag filter). INJECTED into a session at SessionStart and UserPromptSubmit as
`additionalContext` when relevant (bounded BM25 retrieval, local-only). A daily
`precept audit` (once-per-day throttle) surfaces rename / placement / missing-frontmatter /
missing-sources / unfiled-knowledge findings as PENDING proposals (never auto-applied). An
MCP `query_knowledge` tool is still planned.

**Structure.** A `type: knowledge` markdown file IN THE VAULT (frontmatter `updated:` +
`## Sources`; captured files also carry `precept_status: pending` until confirmed) plus one
FTS5 row. Entities = folders, relationships = `[[wikilinks]]`. The legacy
`Note{id,created,title,body,tags[],source}` is the back-compat recall view.

**Infra.** ONE knowledge store: the PRIVATE, CONFIGURABLE vault (`PRECEPT_VAULT`) is the
source of truth (sync-safe markdown); a derived FTS5 `knowledge_index.db` on LOCAL disk
(rebuildable) makes recall fast. The old `~/.precept/notes` silo is retired — `note/recall/
reindex` now operate on the vault-backed index. Not a native Claude Code construct: Precept
owns it. SOFT (recalled/injected, never enforced). Keyword-first; sqlite-vec semantic recall
+ an ANN/HNSW index are deferred (a guarded ANN-watch seam suggests HNSW past ~1M vectors)
until a Recall@k eval demands them.

## 3. CLAUDE.md edit  (SOFT, not built)

**What.** A standing directive or convention ("API handlers live in `src/api/`",
"prefer composition over inheritance"). A soft process: always-on context.

**When/how used.** Loaded at the start of every session as context. Best for
conventions and preferences, never for hard rules (Claude Code: CLAUDE.md is "context,
not enforced configuration, no guarantee of strict compliance").

**Structure.** Precept lesson (`artifact_type=CLAUDE_MD`) -> a marker-delimited block
appended to `~/.claude/CLAUDE.md` (user), `./CLAUDE.md` (project), or a path-scoped
`.claude/rules/*.md` (loads only when matching files are touched). Marker delimiting
lets Precept update or remove its own block atomically without disturbing yours.

**Infra.** Atomic write into the real CLAUDE.md / `.claude/rules/`. SOFT (Claude Code
delivers it as a user message after the system prompt).

## 4. Skill  (SOFT, not built)

**What.** A reusable multi-step procedure: the core "process" artifact ("our release
checklist", "how we scaffold a service", "the way I want PRs described").

**When/how used.** Loaded on demand (progressive disclosure): Claude auto-loads it
when the `description` matches the task, or you invoke `/skill-name`. Costs almost
nothing in context until used, which is why a long procedure belongs here, not in
CLAUDE.md.

**Structure.** Precept lesson (`artifact_type=SKILL`) -> `.claude/skills/<name>/SKILL.md`
with frontmatter `name`, `description` (drives auto-load), optional `allowed-tools`,
`disallowed-tools`, `disable-model-invocation`, `argument-hint`, `model`; the body is
the procedure; optional supporting files (templates, scripts) live in the directory.

**Infra.** `.claude/skills/` (project) or `~/.claude/skills/` (user). SOFT
(model-invoked). Follows the open Agent Skills standard. Note: custom slash commands
are now merged into Skills.

## 5. Agent persona / subagent  (HARD tool-scope + SOFT prompt, not built)

**What.** A saved specialized agent with its own system prompt and a tool allowlist
("security-reviewer", "safe-researcher that can read but never write"). Both a process
(its instructions) and a capability boundary (its tools).

**When/how used.** Claude delegates to it when a task matches its `description`, or you
spawn it via `/agents`. It runs in its own context window and returns a summary.

**Structure.** Precept lesson (`artifact_type=AGENT_PERSONA`) -> `.claude/agents/<name>.md`
with frontmatter `name`, `description` (both required), `tools` (allowlist) or
`disallowedTools` (denylist), `model`, optional `permissionMode`, `isolation`, `color`;
the body is the system prompt. Per-field tier: the `tools` allowlist is **HARD** (a
real capability boundary: a research persona literally cannot Edit or Write), the
system prompt is **SOFT**.

**Infra.** `.claude/agents/` or `~/.claude/agents/`. The tool allowlist also accepts
MCP server patterns (`mcp__server`), so a persona can be scoped off entire servers.

## 6. Output style  (SOFT, not built)

**What.** A persistent role / tone / format that modifies the system prompt ("always
lead with a Mermaid diagram", "act as a data analyst, not an engineer").

**When/how used.** Applies to every response while active. Stronger than CLAUDE.md
(it edits the system prompt itself), but still steering, not enforcement. Only one is
active at a time.

**Structure.** Precept lesson (`artifact_type=OUTPUT_STYLE`) -> `.claude/output-styles/<name>.md`
with frontmatter `name`, `description`, `keep-coding-instructions` (keep Claude Code's
coding behavior or replace it); the body is appended to the system prompt. Activated by
the `outputStyle` setting (Precept would set it on apply).

**Infra.** `.claude/output-styles/` (project) or `~/.claude/output-styles/`. SOFT
(system-prompt level). Takes effect on `/clear` or a new session.

## 7. Slash command  (SOFT, not built; now a Skill variant)

**What.** A saved prompt-macro for a request you repeat ("/ship", "/review-pr").

**When/how used.** User-invoked: `/name [args]`.

**Structure.** Now unified with Skills. Either `.claude/commands/<name>.md` (legacy,
still works) or `.claude/skills/<name>/SKILL.md` with `disable-model-invocation: true`
(user-only). Frontmatter `argument-hint`, `allowed-tools`; the body uses `$ARGUMENTS`
or `$1`, `$2` for parameters. Precept models this as a user-invoked Skill.

**Infra.** `.claude/commands/` or `.claude/skills/`. SOFT (a convenience macro).

## 8. MCP / tool config  (config, not built)

**What.** Which MCP servers and tools are enabled, typically per project ("this repo
always needs the Linear server").

**When/how used.** Resolved at session start; defines the available tool surface.

**Structure.** Precept lesson (`artifact_type=MCP_CONFIG`) -> entries in `.mcp.json`
(project) or `mcpServers` in settings, plus which tools to enable. Pairs with a
permission rule (#9) when you want to *gate* an MCP tool, since config alone enables
but does not enforce.

**Infra.** `.mcp.json` / settings. Configuration, not enforcement.

## 9. Permission profile  (HARD, import built / apply not built)

**What.** A curated, named bundle of allow / deny / ask rules ("read-only audit",
"no network", "no force-push"). Reusable, swappable enforcement presets.

**When/how used.** Enforced by Claude Code on every tool call, independent of the
model, with strict deny-first precedence (a deny in any scope beats any allow, and
beats a hook's allow).

**Structure.** Precept lesson(s) -> a `permissions` block in `settings.json` with
`{allow, deny, ask}` arrays of `Tool(pattern)` rules (`Bash(rm -rf *)`, `Read(.env)`,
`WebFetch(domain:*.internal)`). A "profile" is a named set Precept can apply or remove
as a unit. Caveat (from Claude Code docs): argument-constraining Bash patterns are
bypassable, so for reliable enforcement Precept prefers a PreToolUse hook (#1) when
argument logic matters, and a permission deny only for clean tool+path/domain bans.

**Infra.** `settings.json` `permissions`. HARD (enforced by Claude Code, not the
model). Precept *imports* these (bootstrap parses your `permissions.deny`/`ask` into hard
policies) AND now *writes back* the clean bans it synthesizes from corrections: a clean
tool+path/domain/whole-tool ban compiles to a marker-managed `permissions.deny`/`.ask`
entry (idempotent, atomic, .bak; a sidecar manifest subtracts only Precept's own strings,
never the user's). Curated *named* profiles you apply/remove as a unit remain the
unbuilt half.

---

## How this maps to the platform's three pillars

- **Processes:** #1 Rule, #3 CLAUDE.md, #4 Skill, #5 Agent persona, #6 Output style,
  #7 Slash command, #8 MCP config, #9 Permission profile. (Rules, personas, and
  permission profiles carry the HARD edge; the rest steer.)
- **Entities and data:** #2 Knowledge note today; a typed entity catalog is the
  planned upgrade.
- **Self-improving:** the detect -> review -> compile loop authors and refines all of
  the above from (a) how you work and (b) Precept's own autonomous learning (reading
  best practices / the web on its own judgment), always proposing, never acting
  silently.
