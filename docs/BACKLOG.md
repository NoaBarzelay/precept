# Engineering backlog

Finer-grained open items, deferred from shipped work. Direction-level planning lives in `ROADMAP.md`; this list tracks the smaller follow-ups so they are not lost. Shipped work is recorded in the git history, not here.

## Open

- **Field-level rewrite for variadic commands.** The `rewrite` decision today replaces a whole input field, so a token swap inside a variadic command (`npm install left-pad` to `pnpm install left-pad`) falls back to deny. Add a token-substitution `rewrite_to` shape (a bounded regex replace within one field) so substitution corrections rewrite instead of blocking.
- **LANGUAGE scope matching.** `scope: language` is plumbed but currently behaves as global. Implement detection from the session cwd (`package.json`, `pyproject.toml`) without slowing the hot path.
- **OR-of-tools relevance gates.** A judgment rule's `applies_when` gate targets a single tool (Edit). Support a disjunction (Edit OR Write) so code-quality rules gate on any code mutation; this is a schema change.
- **Review surface beyond the CLI.** Pending proposals are surfaced via hook context injection and approved with `precept keep`. Evaluate an MCP review tool or a small TUI inbox as a lower-friction approval surface. The review gate itself is unchanged.
- **AI-based detection pre-filter.** The per-turn cost gate before DETECT is a recall-biased regex. If observed misses justify it, replace with a cheap model pre-filter; until then the regex keeps per-turn cost near zero.
- **ANN index for knowledge vectors.** Nearest-neighbor over a future `vectors` table is brute-force, which holds to roughly tens of thousands of rows. The daily audit already watches the table size and suggests an HNSW index past the threshold; build it only when the suggestion fires.
