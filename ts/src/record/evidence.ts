// The append-only evidence log (ARCHITECTURE.md section 6.2). The record shape
// is the domain contract (`domain/evidence.ts`); this module owns its
// persistence: one immutable JSON line per observation, never rewritten.

import type { EvidenceRecord } from "../domain/evidence.ts";
import { evidenceLogPath } from "../store/paths.ts";
import { appendLine, readLines } from "./log.ts";

export type { EvidenceRecord } from "../domain/evidence.ts";

export function appendEvidence(record: EvidenceRecord): void {
  appendLine(evidenceLogPath(), record);
}

export function readEvidence(): EvidenceRecord[] {
  return readLines<EvidenceRecord>(evidenceLogPath());
}
