// The Claude Code hook contract adapter (ARCHITECTURE.md sections 5.2, 5.3).
// The only module that knows the host's wire format: it reads an event and
// emits a decision. A second host is a second adapter, not a rewrite. Hand-
// written narrowing over the host's own JSON, no schema library, because the
// interception path that shares this module must stay thin.

/** The subset of hook events the O2 injection path handles. */
export interface UserPromptSubmitEvent {
  readonly kind: "UserPromptSubmit";
  readonly prompt: string;
  readonly cwd?: string;
  readonly sessionId?: string;
}

export interface SessionStartEvent {
  readonly kind: "SessionStart";
  readonly cwd?: string;
  readonly sessionId?: string;
}

export interface OtherEvent {
  readonly kind: "Other";
  readonly name: string;
}

export type HookEvent =
  | UserPromptSubmitEvent
  | SessionStartEvent
  | OtherEvent;

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

/**
 * Parse a hook event from the host. Accepts snake_case (the host's input) and
 * tolerates camelCase. Throws only on non-JSON; an unknown event returns
 * `Other` so a caller can no-op rather than fail.
 */
export function parseEvent(raw: string): HookEvent {
  const o = JSON.parse(raw) as Record<string, unknown>;
  const name = str(o.hook_event_name) ?? str(o.hookEventName) ?? "";
  const cwd = str(o.cwd);
  const sessionId = str(o.session_id) ?? str(o.sessionId);
  if (name === "UserPromptSubmit") {
    return {
      kind: "UserPromptSubmit",
      prompt: str(o.prompt) ?? "",
      ...(cwd !== undefined ? { cwd } : {}),
      ...(sessionId !== undefined ? { sessionId } : {}),
    };
  }
  if (name === "SessionStart") {
    return {
      kind: "SessionStart",
      ...(cwd !== undefined ? { cwd } : {}),
      ...(sessionId !== undefined ? { sessionId } : {}),
    };
  }
  return { kind: "Other", name };
}

/** Output that injects context for a UserPromptSubmit or SessionStart hook. */
export function additionalContextOutput(
  text: string,
  eventName: "UserPromptSubmit" | "SessionStart",
): string {
  return JSON.stringify({
    hookSpecificOutput: { hookEventName: eventName, additionalContext: text },
  });
}

/** Output that injects nothing and lets the turn proceed (the fail-open shape). */
export function emptyOutput(): string {
  return JSON.stringify({ continue: true });
}
