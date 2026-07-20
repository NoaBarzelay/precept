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

/** A rule whose check threw during evaluation: it failed open and must be recorded (N1). */
export interface EnforceFault {
  readonly ruleId: string;
  readonly error: string;
}

export interface Decision {
  readonly outcome: Outcome;
  /** The rule that produced a non-allow outcome. */
  readonly ruleId?: string;
  readonly reason?: string;
  /** Rules that failed open, so the caller can record them (N1/D2). */
  readonly faults: readonly EnforceFault[];
}

const RANK: Record<Outcome, number> = { allow: 0, ask: 1, deny: 2 };

/**
 * Evaluate the applicable rules against the facts and return the strongest
 * outcome. A rule whose check throws is skipped (fail toward allow) but its
 * fault is returned, because fail-open is only defensible if the break is
 * recorded rather than silent (D2).
 */
export function enforce(
  facts: FactRecord,
  rules: readonly CompiledRule[],
): Decision {
  let outcome: Outcome = "allow";
  let ruleId: string | undefined;
  let reason: string | undefined;
  const faults: EnforceFault[] = [];
  for (const rule of rules) {
    let matched = false;
    try {
      matched = evaluate(rule.check, facts);
    } catch (e) {
      faults.push({ ruleId: rule.id, error: e instanceof Error ? e.message : String(e) });
      continue; // a broken rule never blocks, but it is recorded
    }
    if (!matched) continue;
    if (RANK[rule.outcome] > RANK[outcome]) {
      outcome = rule.outcome;
      ruleId = rule.id;
      reason = rule.reason;
    }
  }
  return {
    outcome,
    ...(ruleId !== undefined ? { ruleId } : {}),
    ...(reason !== undefined ? { reason } : {}),
    faults,
  };
}
