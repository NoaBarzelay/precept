// The observation entrypoint (ARCHITECTURE.md section 5.4). It runs off the
// interactive turn, makes no decision, and never fails the turn: a recording
// fault is noted, not raised (D2).
//
// On PostToolUse it records the call's facts to the tool-call history that
// authoring-time validation and the review gate read. On SessionEnd it drafts
// evidence from the finished session transcript (host/transcript): the
// surrounding turns of each human-typed turn, and any silent edit of the
// agent's output (R1.1). Evidence ids are content-derived and appended only if
// unseen, so a re-fired SessionEnd (a resumed session ending again) drafts
// nothing twice without needing a cursor.
//
// When new evidence lands and the model backend is enabled, SessionEnd kicks
// detection in a detached background process so the review queue fills on its
// own (the objective's "continuous, mostly-implicit" half). It is fire-and-
// forget and off the turn: the costly pass never becomes latency the user feels
// (R1.1, R1.5), and it is gated on `PRECEPT_INFERENCE=cli` so the learning loop
// spends tokens only when the user has opted in (N4, the ceiling they control).

import { resolve } from "node:path";
import {
  assembleFacts,
  emptyOutput,
  parseEvent,
  type SessionEndEvent,
} from "./host/claude_code.ts";
import { ingestTranscriptFile } from "./host/transcript.ts";
import { appendEvidence, readEvidence } from "./record/evidence.ts";
import { noteFault } from "./record/fault.ts";
import { recordCall } from "./record/history.ts";

/** The self-improvement loop runs automatically only when the backend is on. */
export function shouldTriggerDetection(appended: number): boolean {
  return (
    appended > 0 &&
    process.env.PRECEPT_INFERENCE === "cli" &&
    process.env.PRECEPT_INFERENCE_SUBPROCESS !== "1"
  );
}

/** Handle one hook event given its raw JSON, returning the hook's stdout. */
export function runObservation(raw: string): string {
  if (process.env.PRECEPT_INFERENCE_SUBPROCESS === "1") return emptyOutput();
  try {
    const event = parseEvent(raw);
    if (event.kind === "PostToolUse") {
      recordCall(assembleFacts(event));
    } else if (event.kind === "SessionEnd") {
      const appended = observeSession(event);
      if (shouldTriggerDetection(appended)) spawnDetection();
    }
  } catch (error) {
    noteFault("observation", error);
  }
  return emptyOutput();
}

/**
 * Kick `precept detect` in a detached background process and return at once, so
 * the finished session's evidence becomes queued candidates without blocking the
 * SessionEnd hook or the user's shell. Fail-open: a spawn error is noted, never
 * raised (D2).
 */
function spawnDetection(): void {
  try {
    const cli = resolve(import.meta.dir, "cli.ts");
    const child = Bun.spawn([process.execPath, cli, "detect"], {
      stdin: "ignore",
      stdout: "ignore",
      stderr: "ignore",
    });
    child.unref(); // do not keep the hook process alive waiting on it
  } catch (error) {
    noteFault("observation.detect", error);
  }
}

/**
 * Draft and record evidence from a finished session. Returns the number of new
 * evidence records appended (0 when there is no transcript or nothing new).
 */
export function observeSession(event: SessionEndEvent): number {
  if (event.transcriptPath === undefined) return 0;
  const session = event.sessionId ?? event.transcriptPath;
  const evidence = ingestTranscriptFile(event.transcriptPath, { session });
  const seen = new Set(readEvidence().map((e) => e.id));
  let appended = 0;
  for (const record of evidence) {
    if (seen.has(record.id)) continue; // content-derived id: never drafts twice
    appendEvidence(record);
    seen.add(record.id);
    appended++;
  }
  return appended;
}

if (import.meta.main) {
  const raw = await Bun.stdin.text();
  process.stdout.write(runObservation(raw));
}
