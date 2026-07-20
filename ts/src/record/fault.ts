// Fault recording (ARCHITECTURE.md section 6.4, N1). The enforcement path fails
// open, so every fault is recorded against the rule that did not fire (or the
// stage that failed), because fail-open is only defensible if the break is
// visible rather than silent. Recording is itself best-effort: it never throws.

import { faultsLogPath } from "../store/paths.ts";
import { appendLine } from "./log.ts";

export interface FaultRecord {
  readonly at: string;
  readonly stage: string;
  readonly ruleId?: string;
  readonly error: string;
}

export function noteFault(stage: string, error: unknown, ruleId?: string): void {
  try {
    appendLine(faultsLogPath(), {
      at: new Date().toISOString(),
      stage,
      ...(ruleId !== undefined ? { ruleId } : {}),
      error: error instanceof Error ? error.message : String(error),
    });
  } catch {
    // best-effort; never let recording a fault cause one
  }
}
