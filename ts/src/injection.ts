// The injection entrypoint (ARCHITECTURE.md section 5.4). Two events, two jobs.
//
// On UserPromptSubmit, retrieve the knowledge relevant to the prompt and inject
// it as additionalContext.
//
// On SessionStart, report the review queue (R1.8). The queue is the one step of
// the loop that needs a human, and until now nothing asked for it, so candidates
// accumulated unreviewed while the catalog stayed empty. The prompt is bounded
// and throttled (see record/backlog), and it asks for an interactive walk rather
// than a dump, because a wall of queued text is what makes a reviewer stop
// reading.
//
// An orchestration entrypoint: it drives the host adapter, retrieve, and the
// queue. Fails open: any error injects nothing and lets the turn proceed (N1),
// because a missed injection costs far less than a wedged turn.

import {
  additionalContextOutput,
  emptyOutput,
  parseEvent,
} from "./host/claude_code.ts";
import { backlogPrompt, stampPrompted } from "./record/backlog.ts";
import { assembleContext, retrieve } from "./retrieve/retrieve.ts";

/** Handle one hook event given its raw JSON, returning the hook's stdout. */
export function runInjection(raw: string): string {
  if (process.env.PRECEPT_INFERENCE_SUBPROCESS === "1") return emptyOutput();
  try {
    const event = parseEvent(raw);
    if (event.kind === "SessionStart") {
      const prompt = backlogPrompt();
      if (prompt === "") return emptyOutput();
      // Stamp only once the text is actually being returned, so a session that
      // injects nothing does not start the quiet interval.
      stampPrompted();
      return additionalContextOutput(prompt, "SessionStart");
    }
    if (event.kind !== "UserPromptSubmit") return emptyOutput();
    const hits = retrieve(event.prompt);
    const context = assembleContext(hits);
    return context === ""
      ? emptyOutput()
      : additionalContextOutput(context, "UserPromptSubmit");
  } catch {
    return emptyOutput();
  }
}

if (import.meta.main) {
  const raw = await Bun.stdin.text();
  process.stdout.write(runInjection(raw));
}
