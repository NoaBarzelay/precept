// The interception entrypoint: the enforcement hot path (ARCHITECTURE.md
// sections 5.4, 6.4, D1). On PreToolUse it assembles the facts, reads the
// compiled projection, decides, and emits a permission decision. It links no
// model, no schema library, and no card parser; it reads a plain-JSON
// projection through a fixed evaluator. It fails open on any fault and records
// it, because a wedged turn costs more than a missed block (N1).

import { enforce } from "./domain/enforce.ts";
import {
  assembleFacts,
  emptyOutput,
  parseEvent,
  permissionOutput,
} from "./host/claude_code.ts";
import { readProjection } from "./projection/projection.ts";
import { noteFault } from "./record/fault.ts";

/** Handle one PreToolUse event given its raw JSON, returning the hook's stdout. */
export function runInterception(raw: string): string {
  try {
    const event = parseEvent(raw);
    if (event.kind !== "PreToolUse") return emptyOutput();
    const facts = assembleFacts(event);
    const rules = readProjection();
    const decision = enforce(facts, rules);
    if (decision.outcome === "allow") return emptyOutput();
    return permissionOutput(
      decision.outcome,
      decision.reason ?? "",
      decision.ruleId,
    );
  } catch (error) {
    noteFault("interception", error);
    return emptyOutput();
  }
}

if (import.meta.main) {
  const raw = await Bun.stdin.text();
  process.stdout.write(runInterception(raw));
}
