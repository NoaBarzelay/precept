// The observation entrypoint (ARCHITECTURE.md section 5.4). It runs off the
// interactive turn, makes no decision, and never fails the turn: a recording
// fault is noted, not raised (D2).
//
// On PostToolUse it records the call's facts to the tool-call history that
// authoring-time validation and the review gate read. On SessionEnd it drafts
// evidence from the finished session transcript (host/transcript): the
// surrounding turns of each human-typed turn, and any silent edit of the
// agent's output (R1.1). A per-session cursor makes a re-fired SessionEnd
// idempotent, and evidence is deduped by id, so nothing is drafted twice.

import {
  assembleFacts,
  emptyOutput,
  parseEvent,
  type SessionEndEvent,
} from "./host/claude_code.ts";
import { ingestTranscriptFile } from "./host/transcript.ts";
import { readCursor, writeCursor } from "./record/cursor.ts";
import { appendEvidence, readEvidence } from "./record/evidence.ts";
import { noteFault } from "./record/fault.ts";
import { recordCall } from "./record/history.ts";

/** Handle one hook event given its raw JSON, returning the hook's stdout. */
export function runObservation(raw: string): string {
  if (process.env.PRECEPT_INFERENCE_SUBPROCESS === "1") return emptyOutput();
  try {
    const event = parseEvent(raw);
    if (event.kind === "PostToolUse") {
      recordCall(assembleFacts(event));
    } else if (event.kind === "SessionEnd") {
      observeSession(event);
    }
  } catch (error) {
    noteFault("observation", error);
  }
  return emptyOutput();
}

/**
 * Draft and record evidence from a finished session. Returns the number of new
 * evidence records appended (0 when there is no transcript or nothing new).
 */
export function observeSession(event: SessionEndEvent): number {
  if (event.transcriptPath === undefined) return 0;
  const session = event.sessionId ?? event.transcriptPath;
  const since = readCursor(session);
  const { evidence, consumed } = ingestTranscriptFile(
    event.transcriptPath,
    { session },
    { since },
  );
  const seen = new Set(readEvidence().map((e) => e.id));
  let appended = 0;
  for (const record of evidence) {
    if (seen.has(record.id)) continue; // deduped: a lost cursor never doubles
    appendEvidence(record);
    seen.add(record.id);
    appended++;
  }
  writeCursor(session, consumed);
  return appended;
}

if (import.meta.main) {
  const raw = await Bun.stdin.text();
  process.stdout.write(runObservation(raw));
}
