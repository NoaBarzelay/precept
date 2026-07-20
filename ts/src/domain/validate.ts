// Evidence-based validation of a check (DECISIONS.md, ARCHITECTURE.md 5.1).
// Instead of proving properties of a check symbolically, validate it against
// recorded traffic. These are pure functions over a check and a set of calls;
// loading the history is a caller's job. Every evaluation is guarded, so a
// malformed check counts as no-match rather than throwing.

import { type Check, evaluate } from "./check.ts";
import type { FactRecord } from "./facts.ts";

function matches(check: Check, facts: FactRecord): boolean {
  try {
    return evaluate(check, facts);
  } catch {
    return false;
  }
}

/**
 * Reachability (N5, D3): the check matches at least one concrete call, drawn
 * from recorded history or a reviewed example. A check that can never fire is
 * not allowed to claim enforcement.
 */
export function reachable(
  check: Check,
  calls: readonly FactRecord[],
  examples: readonly FactRecord[] = [],
): boolean {
  return (
    calls.some((f) => matches(check, f)) ||
    examples.some((f) => matches(check, f))
  );
}

export interface Firing {
  readonly count: number;
  /** Up to `limit` calls the check fired on, for the reviewer to judge. */
  readonly examples: readonly FactRecord[];
}

/**
 * How broad a check is: how many recorded calls it would have fired on, and a
 * sample of them. This is the review surface a rationale panel cannot give, and
 * the number a proof cannot compute.
 */
export function firing(
  check: Check,
  calls: readonly FactRecord[],
  limit = 3,
): Firing {
  let count = 0;
  const examples: FactRecord[] = [];
  for (const f of calls) {
    if (matches(check, f)) {
      count++;
      if (examples.length < limit) examples.push(f);
    }
  }
  return { count, examples };
}

/**
 * Subsumption (R1.4, Risk 4): every recorded call matching `narrower` also
 * matches `broader`, and `broader` fires at least as often, so the narrower
 * check adds no coverage over history and is a redundancy candidate. Advisory:
 * it only sees calls that occurred.
 */
export function subsumes(
  broader: Check,
  narrower: Check,
  calls: readonly FactRecord[],
): boolean {
  let sawNarrower = false;
  for (const f of calls) {
    if (matches(narrower, f)) {
      sawNarrower = true;
      if (!matches(broader, f)) return false;
    }
  }
  return sawNarrower;
}
