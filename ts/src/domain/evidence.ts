// The evidence record: one immutable, provenance-tagged observation
// (ARCHITECTURE.md section 6.2). The type lives in `domain` so both `host`
// (which reads a session transcript and drafts evidence) and `record` (which
// appends and reads the log) can reference the contract without crossing the
// dependency rule. Evidence holds the surrounding turns verbatim (not a
// summary, because summarizing at capture destroys the raw signal R1.14's
// re-examination depends on), and, for a silent-edit signal, the agent's output
// and the file's final state so the diff is reconstructable later.

import type { SignalKind } from "./entry.ts";

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
