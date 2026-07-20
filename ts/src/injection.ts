// The injection entrypoint (ARCHITECTURE.md section 5.4). On UserPromptSubmit,
// retrieve the knowledge relevant to the prompt and inject it as
// additionalContext. An orchestration entrypoint: it drives the host adapter
// and retrieve. Fails open: any error injects nothing and lets the turn
// proceed (N1), because a missed injection costs far less than a wedged turn.

import {
  additionalContextOutput,
  emptyOutput,
  parseEvent,
} from "./host/claude_code.ts";
import { assembleContext, retrieve } from "./retrieve/retrieve.ts";

/** Handle one hook event given its raw JSON, returning the hook's stdout. */
export function runInjection(raw: string): string {
  if (process.env.PRECEPT_INFERENCE_SUBPROCESS === "1") return emptyOutput();
  try {
    const event = parseEvent(raw);
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
