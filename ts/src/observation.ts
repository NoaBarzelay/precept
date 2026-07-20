// The observation entrypoint (ARCHITECTURE.md section 5.4). On PostToolUse it
// records the call's facts to the tool-call history that authoring-time
// validation and the review gate read. It runs off the interactive turn, makes
// no decision, and never fails the turn: a recording fault is noted, not raised.

import {
  assembleFacts,
  emptyOutput,
  parseEvent,
} from "./host/claude_code.ts";
import { noteFault } from "./record/fault.ts";
import { recordCall } from "./record/history.ts";

/** Handle one hook event given its raw JSON, returning the hook's stdout. */
export function runObservation(raw: string): string {
  try {
    const event = parseEvent(raw);
    if (event.kind === "PostToolUse") {
      recordCall(assembleFacts(event));
    }
  } catch (error) {
    noteFault("observation", error);
  }
  return emptyOutput();
}

if (import.meta.main) {
  const raw = await Bun.stdin.text();
  process.stdout.write(runObservation(raw));
}
