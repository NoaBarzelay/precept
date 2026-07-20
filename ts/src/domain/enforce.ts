// The enforcement evaluator (ARCHITECTURE.md section 6.4). Pure and total:
// given the assembled facts and the compiled rules, it decides. It links no
// model and touches no IO, so it can run on the interception hot path within
// the D1 budget.
//
// Decisions combine as an order, not a sequence: deny > ask > allow. The
// strongest outcome across the applicable rules wins, independent of evaluation
// order, so adding a deny can never weaken enforcement.

import { type Check, evaluate } from "./check.ts";
import type { FactRecord } from "./facts.ts";

export type Outcome = "deny" | "ask" | "allow";

/** One rule as it appears in the compiled projection the hot path reads. */
export interface CompiledRule {
  readonly id: string;
  readonly check: Check;
  /** What a match yields: an operational rule denies, a probationary one asks. */
  readonly outcome: "deny" | "ask";
  readonly reason: string;
}

export interface Decision {
  readonly outcome: Outcome;
  /** The rule that produced a non-allow outcome. */
  readonly ruleId?: string;
  readonly reason?: string;
}

const RANK: Record<Outcome, number> = { allow: 0, ask: 1, deny: 2 };

/**
 * Evaluate the applicable rules against the facts and return the strongest
 * outcome. A rule whose check throws is skipped (fail toward allow), so one
 * malformed rule cannot wedge the call.
 */
export function enforce(
  facts: FactRecord,
  rules: readonly CompiledRule[],
): Decision {
  let best: Decision = { outcome: "allow" };
  for (const rule of rules) {
    let matched = false;
    try {
      matched = evaluate(rule.check, facts);
    } catch {
      matched = false; // a broken rule never blocks
    }
    if (!matched) continue;
    if (RANK[rule.outcome] > RANK[best.outcome]) {
      best = { outcome: rule.outcome, ruleId: rule.id, reason: rule.reason };
    }
  }
  return best;
}
