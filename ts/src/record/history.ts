// The recorded tool-call history (ARCHITECTURE.md section 5.1, DECISIONS.md:
// "validate a check against recorded tool-call history, not by symbolic
// proof"). Append-only, local disk only, one line per guarded call. It is what
// authoring-time validation scans and what the review gate shows.

import type { FactRecord } from "../domain/facts.ts";
import { historyLogPath } from "../store/paths.ts";
import { appendLine, readLines } from "./log.ts";

export interface CallRecord {
  readonly at: string;
  readonly facts: FactRecord;
}

/** Append one guarded call's facts to the history. */
export function recordCall(facts: FactRecord): void {
  appendLine(historyLogPath(), { at: new Date().toISOString(), facts });
}

/** All recorded calls. */
export function readHistory(): CallRecord[] {
  return readLines<CallRecord>(historyLogPath());
}
