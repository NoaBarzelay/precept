// The append-only proposal ledger: which evidence has already been sent to the
// model (ARCHITECTURE.md section 6.1, Risk 5).
//
// Detection reads the whole evidence log on every run, because evidence is
// append-only and has no cursor (the same choice `host/transcript` makes: a
// cursor goes stale under a compacted or rotated log, a content-derived id does
// not). Without a record of what was already proposed, every run re-sends every
// past window to the model and pays for it again, and the review queue fills
// with duplicates of the same window.
//
// The queue and the decision log cannot stand in for this ledger: an abstention
// leaves no trace in either, and abstention is the common outcome, so the bulk
// of the repeat spend would go unrecorded. This ledger records the send, not the
// outcome.
//
// Filtered evidence is deliberately absent: the pre-filter costs nothing to
// re-run, and the R1.14 hindsight pass wants to revisit what the live gate
// skipped.

import { proposedLogPath } from "../store/paths.ts";
import { appendLine, readLines } from "./log.ts";

/** One immutable line per evidence window sent to the model. */
export interface ProposalRecord {
  readonly evidenceId: string;
  readonly at: string;
}

export function appendProposed(
  evidenceId: string,
  at: string = new Date().toISOString(),
): void {
  appendLine(proposedLogPath(), { evidenceId, at });
}

/** Every evidence id already sent to the model, in one pass over the log. */
export function readProposed(): Set<string> {
  return new Set(
    readLines<ProposalRecord>(proposedLogPath()).map((r) => r.evidenceId),
  );
}
