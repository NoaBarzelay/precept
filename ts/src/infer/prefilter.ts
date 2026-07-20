// The cost gate before the model (ARCHITECTURE.md section 6.2; Risk 5, and
// R1.18's "a cheap deterministic relevance test decides whether the turn needs
// a model call at all"). The transcript reader records evidence broadly, so the
// R1.14 hindsight pass keeps the raw signal; this decides which of that evidence
// is worth a model call now.
//
// Recall-biased by design: a needless call is cheap, a missed durable preference
// is not, and even a miss is recoverable because the evidence stays in the log
// for the hindsight pass. So the gate only skips the clear one-off: a plain task
// request with none of the language a standing preference or a project fact
// carries.

import type { EvidenceRecord } from "../record/evidence.ts";

// Cues that a plain instruction states something durable: a standing preference,
// a convention, or a project fact, rather than a one-off task. Deliberately
// broad. An imperative correction is already tagged `correction` upstream and
// never reaches this test.
const DURABLE_CUES =
  /\b(always|never|prefer|preferred|avoid|must|should|ensure|only|use[sd]?|using|run[s]?|deploy[s]?|from now on|going forward|note that|convention|standard|rule|in this (repo|project|codebase))\b/i;

/**
 * Whether an evidence record warrants a model call now. Every signal kind but a
 * plain instruction is inherently candidate-bearing and always proposes; an
 * instruction proposes only when its own turn carries a durable cue. The human
 * turn is the last segment of the window, so the test reads that rather than the
 * surrounding context.
 */
export function worthProposing(evidence: EvidenceRecord): boolean {
  if (evidence.signalKind !== "instruction") return true;
  const humanTurn = evidence.turns.split("\n---\n").at(-1) ?? evidence.turns;
  return DURABLE_CUES.test(humanTurn);
}
