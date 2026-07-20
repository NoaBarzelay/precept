// The decision record and its append-only log (ARCHITECTURE.md sections 6.1,
// 6.6, N6, N7). Nothing reaches the catalog without a decision record. The
// record is immutable and carries the proposed candidate, what was committed,
// and the delta between them, which is what correcting the inference consumes
// (R1.13).

import type { Candidate } from "../domain/candidate.ts";
import { decisionsLogPath } from "../store/paths.ts";
import { appendLine, readLines } from "./log.ts";

export type ReviewAction = "keep" | "dismiss" | "correct";

/** The proposed-vs-committed delta: the field names that changed, with values. */
export interface Delta {
  readonly changed: readonly string[];
  readonly proposed: Readonly<Record<string, unknown>>;
  readonly committed: Readonly<Record<string, unknown>>;
}

export interface DecisionRecord {
  readonly id: string;
  readonly at: string;
  readonly action: ReviewAction;
  readonly proposed: Candidate;
  /** Present on keep and correct; the entry id that was written. */
  readonly entryId?: string;
  /** Present on correct; the delta the reviewer introduced. */
  readonly delta?: Delta;
  /** Present on dismiss. */
  readonly reason?: string;
  readonly evidenceId?: string;
}

export function appendDecision(record: DecisionRecord): void {
  appendLine(decisionsLogPath(), record);
}

export function readDecisions(): DecisionRecord[] {
  return readLines<DecisionRecord>(decisionsLogPath());
}

/** Compute the field-level delta between a proposed and a committed candidate. */
export function deltaBetween(proposed: Candidate, committed: Candidate): Delta {
  const pRec = proposed as unknown as Record<string, unknown>;
  const cRec = committed as unknown as Record<string, unknown>;
  const keys = new Set([...Object.keys(pRec), ...Object.keys(cRec)]);
  const changed: string[] = [];
  const p: Record<string, unknown> = {};
  const c: Record<string, unknown> = {};
  for (const k of keys) {
    const pv = pRec[k];
    const cv = cRec[k];
    if (JSON.stringify(pv) !== JSON.stringify(cv)) {
      changed.push(k);
      p[k] = pv;
      c[k] = cv;
    }
  }
  return { changed, proposed: p, committed: c };
}
