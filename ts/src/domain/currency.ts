// Pure currency/governance helpers (ARCHITECTURE.md section 6.5; Risk 4). The
// lifecycle transitions themselves (`retire`, `supersede`, `isExpired`) live in
// `entry` beside the other lifecycle operations; these are the selection
// predicates a maintenance or review pass runs over a set of entries. Pure over
// domain types, so they stay in the leaf and the orchestration (retrieval, the
// sweep) is a caller's job.

import type { Candidate } from "./candidate.ts";
import { type Entry, isExpired, isLive, type Scope } from "./entry.ts";

/** Two scopes are the same when they name the same target. */
function sameScope(a: Scope, b: Scope): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Live entries that plausibly conflict with a proposed candidate (R1.4): same
 * kind and same scope. The similarity itself is the caller's lexical retrieval;
 * this applies the kind/scope gate so the reviewer sees only real overlaps, not
 * every keyword match. Advisory: the reviewer reconciles (keep-and-supersede,
 * keep-both, or dismiss).
 */
export function conflictsAmong(
  candidate: Candidate,
  entries: readonly Entry[],
): Entry[] {
  return entries.filter(
    (e) => isLive(e) && e.kind === candidate.kind && sameScope(e.scope, candidate.scope),
  );
}

/**
 * Active entries whose deliberate expiry has passed as of `today` (ISO date):
 * the maintenance sweep retires these (R1.9).
 */
export function expired(entries: readonly Entry[], today: string): Entry[] {
  return entries.filter((e) => e.status === "active" && isExpired(e, today));
}
