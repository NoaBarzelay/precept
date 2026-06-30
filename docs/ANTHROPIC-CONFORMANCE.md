# Anthropic best-practice conformance audit

Audits Precept against Anthropic's OWN documented guidance for **creating**, **retrieving**,
and **configuring** agent rules/memory. Verdict legend: ✅ match · ◐ partial / roadmapped ·
gap → fixed this pass.

Sources: [prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices),
[Claude Code memory](https://code.claude.com/docs/en/memory),
[Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
[context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool),
[hooks](https://code.claude.com/docs/en/hooks), [permissions](https://code.claude.com/docs/en/permissions),
[settings](https://code.claude.com/docs/en/settings).

## Axis 1 — Creating rules

| Anthropic says | Precept | verdict |
|---|---|---|
| Prefer POSITIVE instructions ("do X") over negatives | DETECT requires `what_to_do_instead` to be "a positive target (prefer-Y), not only a prohibition"; the convention bullet IS that field | ✅ |
| Be specific/concrete and verifiable | DETECT extracts a concrete target; synthesizer prefers exact matchers and declines vague ones (fail-closed) | ✅ (model-dependent at extraction) |
| Markdown structure (headers/bullets) for memory | `render_file` emits a header + bullet list | ✅ |
| "Would removing this cause a mistake?" — only keep load-bearing rules | The human keep/veto gate is exactly this test; governance `decay` retires never-fired rules | ✅ |
| Don't over-use emphasis (IMPORTANT/YOU MUST) | `render_file` adds no emphasis markers | ✅ |
| No conflicting instructions across files | `governance.detect_conflicts` (LLM judge) flags contradictions | ◐ (built for rules; conventions don't fire, so weaker signal) |
| Keep a memory file **under ~200 lines** | A GLOBAL conventions file aggregated all active conventions with no bound | gap → **fixed**: `convention.oversize_files` + a `precept doctor` warning past `MAX_RECOMMENDED_LINES=200` |
| Multi-step procedures belong in a Skill, not memory | Conventions are single directives; procedures route to the (unbuilt) Skill artifact | ◐ (router under-built; see CONVENTION-ARTIFACT.md) |

## Axis 2 — Retrieving rules

| Anthropic says | Precept | verdict |
|---|---|---|
| Load only what's needed; just-in-time, finite context | LANGUAGE conventions are `paths:`-scoped (lazy). GLOBAL conventions are always-on | ◐ → roadmapped P1 (activity-keyed retrieval via the knowledge seam) |
| Path-scope rules so they load only for matching files | `paths:` glob frontmatter on LANGUAGE files | ✅ |
| Lost-in-the-middle: keep instructions short, near a boundary | Small dedicated files keep each convention near the top of its own file | ◐ (depends on the leanness guardrail now added) |
| Cross-session persistent memory (memory tool / MEMORY.md) | Precept IS a cross-session memory system (the catalog); overlaps native `MEMORY.md` | ◐ (overlap noted; Precept's edge = human gate + typed catalog + HARD path) |
| Smallest high-signal token set | Convention bullets are terse single lines | ✅ (per-item); ◐ (in aggregate, until P1 retrieval) |

## Axis 3 — Configuring rules

| Anthropic says | Precept | verdict |
|---|---|---|
| Hooks are the deterministic/enforced layer; CLAUDE.md/rules are context, not enforced | Precept's HARD/SOFT honesty backbone is exactly this; only claims enforcement for hooks/permissions | ✅ (core thesis) |
| Hook contract: exit 0 + JSON (`decision`/`additionalContext`/...); exit 2 blocks | `adapters/claude_code` emits the JSON contract; hooks fail-open exit 0; uses `additionalContext`, `decision: block`, `updatedInput` | ✅ (verified, DECISIONS.md) |
| Permission precedence deny > ask > allow; a deny anywhere wins | `resolve_decisions` / `_PRECEDENCE`: deny > ask > rewrite > allow | ✅ |
| Permission rule syntax: `Tool(spec)`, `WebFetch(domain:)`, path globs | `synthesize._as_permission_rule` emits exactly these for clean bans | ✅ |
| **Bash arg-pattern permissions are bypassable** — use a hook | `_as_permission_rule` EXCLUDES Bash on purpose; a Bash ban stays a PreToolUse hook | ✅ (explicitly handled) |
| Tools writing config should own a file / atomic replace, not in-place patch | `safety.atomic_write_text` (temp→fsync→os.replace) + `.bak`; marker-managed permissions; owns its rules files | ✅ |
| Permissions/hooks live-reload; tell the user when a restart/new session is needed | `keep` reports conventions are "loaded as context next session"; `install` says restart sessions | ✅ |
| Managed settings (MDM) are the non-overridable layer | Not used — Precept is a user-level tool, not enterprise MDM | n/a |

## Summary

- **Configuration (Axis 3): strong, near-complete match.** Precept's HARD/SOFT split, hook
  contract, permission precedence, the Bash-bypass handling, and atomic owned-file writes all
  line up with Anthropic's guidance. This is the most mature part.
- **Creating (Axis 1): mostly matched.** Positive-instruction extraction, the review gate as
  the "would removing this cause a mistake?" test, and markdown structure all conform. The
  one concrete gap (no leanness bound) is **fixed this pass** with a doctor warning.
- **Retrieving (Axis 2): the real open work.** Anthropic's just-in-time / finite-context
  guidance is met for LANGUAGE (path-scoped) but not for GLOBAL (always-on). The fix is the
  roadmapped P1 activity-keyed retrieval (CONVENTION-ARTIFACT.md), reusing the knowledge
  retrieval seam.

### Fixes applied this pass
- Leanness guardrail: `convention.oversize_files` + `precept doctor` warning past 200 lines
  (Anthropic's keep-memory-short guidance, made operational).
- `convention.is_managed` now excludes a convention that also compiled to a HARD policy
  (no double-implementation of one learning as both a gate and a soft reminder).
