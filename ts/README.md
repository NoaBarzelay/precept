# Precept (TypeScript rebuild)

The TypeScript on Bun rebuild of Precept, built as a strangler over the shared markdown catalog. The product spec is [../README.md](../README.md); the design this implements is [../ARCHITECTURE.md](../ARCHITECTURE.md); load-bearing decisions are in [../DECISIONS.md](../DECISIONS.md).

Delivery is knowledge-first (Objective O2), then the hot enforcement path, then preference-enforcement authoring (Objective O1). See ARCHITECTURE.md section 10.

## Module map

The dependency rule (ARCHITECTURE.md section 5.3), enforced by `test/arch.test.ts`:

```
domain          imports nothing
store           imports domain
host, record    import domain, store
retrieve        imports domain, store
infer, gate,
eval, cli       import domain, store, retrieve, record
```

- `domain` the entry model, the check language and its evaluator, validity, lifecycle. Imports nothing.
- `store` on-disk card layout, atomic writes, the frontmatter typed contract, schema version, the three storage tiers.
- `retrieve` index, rank, budget, and assemble the injected slice.
- `host` the Claude Code contract (the only module that knows it).
- `infer` the model backend (the only module that reaches the network).
- `gate` the human review gate.
- `record` provenance, telemetry, cost, latency.
- `eval` enforcement and retrieval quality.

## Develop

```
bun install
bun test          # the whole suite, offline
bun run typecheck # tsc --noEmit
bun run arch      # the dependency-rule fitness function
```
