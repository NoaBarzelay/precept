// The evidence record and its append-only log (ARCHITECTURE.md section 6.2).
// Evidence holds the surrounding turns verbatim (not a summary, because
// summarizing at capture destroys the raw signal R1.14 depends on), the
// provenance tag, and, for a silent-edit signal, the agent's output and the
// file's final state so the diff is reconstructable later. Never rewritten.

import type { SignalKind } from "../domain/entry.ts";
import { evidenceLogPath } from "../store/paths.ts";
import { appendLine, readLines } from "./log.ts";

export interface EvidenceRecord {
  readonly id: string;
  /** ISO timestamp. */
  readonly at: string;
  readonly signalKind: SignalKind;
  /** The surrounding turns, verbatim. */
  readonly turns: string;
  readonly session: string;
  readonly repository?: string;
  /** For a silent-edit signal: what the agent wrote. */
  readonly agentOutput?: string;
  /** For a silent-edit signal: the file's final state after the user's edit. */
  readonly finalState?: string;
}

export function appendEvidence(record: EvidenceRecord): void {
  appendLine(evidenceLogPath(), record);
}

export function readEvidence(): EvidenceRecord[] {
  return readLines<EvidenceRecord>(evidenceLogPath());
}
