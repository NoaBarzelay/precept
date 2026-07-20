// The Claude Code hook contract adapter (ARCHITECTURE.md sections 5.2, 5.3).
// The only module that knows the host's wire format: it reads an event and
// emits a decision. A second host is a second adapter, not a rewrite. Hand-
// written narrowing over the host's own JSON, no schema library, because the
// interception path that shares this module must stay thin.

import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import type { FactRecord, FactValue, PermissionMode } from "../domain/facts.ts";
import type { Outcome } from "../domain/enforce.ts";

/** The subset of hook events the O2 injection path handles. */
export interface UserPromptSubmitEvent {
  readonly kind: "UserPromptSubmit";
  readonly prompt: string;
  readonly cwd?: string;
  readonly sessionId?: string;
}

export interface PreToolUseEvent {
  readonly kind: "PreToolUse";
  readonly toolName: string;
  readonly toolInput: Readonly<Record<string, unknown>>;
  readonly cwd?: string;
  readonly permissionMode?: string;
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
  | PreToolUseEvent
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
  if (name === "PreToolUse") {
    const toolInput =
      typeof o.tool_input === "object" && o.tool_input !== null
        ? (o.tool_input as Record<string, unknown>)
        : {};
    return {
      kind: "PreToolUse",
      toolName: str(o.tool_name) ?? "",
      toolInput,
      ...(cwd !== undefined ? { cwd } : {}),
      ...(str(o.permission_mode) !== undefined
        ? { permissionMode: str(o.permission_mode) }
        : {}),
    };
  }
  return { kind: "Other", name };
}

const PERMISSION_MODES = new Set([
  "default",
  "acceptEdits",
  "bypassPermissions",
  "plan",
]);

// Tool-input keys that name a path the call touches.
const PATH_KEYS = ["file_path", "path", "notebook_path"];

/**
 * Assemble the immutable fact record for a PreToolUse event (ARCHITECTURE 5.1).
 * The one filesystem read the interception path makes is resolving the
 * repository and branch from cwd; everything else comes from the event.
 */
export function assembleFacts(event: PreToolUseEvent): FactRecord {
  const toolInput: Record<string, FactValue> = {};
  for (const [k, v] of Object.entries(event.toolInput)) {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      toolInput[k] = v;
    }
  }
  let path: string | undefined;
  for (const key of PATH_KEYS) {
    const v = event.toolInput[key];
    if (typeof v === "string") {
      path = v;
      break;
    }
  }
  const git = event.cwd !== undefined ? resolveGit(event.cwd) : undefined;
  const mode =
    event.permissionMode !== undefined && PERMISSION_MODES.has(event.permissionMode)
      ? (event.permissionMode as PermissionMode)
      : "default";
  return {
    toolName: event.toolName,
    toolInput,
    ...(path !== undefined ? { path } : {}),
    ...(git?.repository !== undefined ? { repository: git.repository } : {}),
    ...(git?.branch !== undefined ? { branch: git.branch } : {}),
    permissionMode: mode,
  };
}

/** Find the nearest enclosing git repo and its current branch, if any. */
function resolveGit(cwd: string): { repository?: string; branch?: string } {
  let dir = cwd;
  for (;;) {
    const gitDir = join(dir, ".git");
    if (existsSync(gitDir)) {
      const repository = basename(dir);
      let branch: string | undefined;
      try {
        const head = readFileSync(join(gitDir, "HEAD"), "utf8").trim();
        const m = /^ref:\s*refs\/heads\/(.+)$/.exec(head);
        if (m !== null) branch = m[1];
      } catch {
        // detached head or unreadable; leave branch undefined
      }
      return { repository, ...(branch !== undefined ? { branch } : {}) };
    }
    const parent = dirname(dir);
    if (parent === dir) return {};
    dir = parent;
  }
}

/** Output that emits a permission decision for a PreToolUse hook. */
export function permissionOutput(
  decision: Outcome,
  reason: string,
  ruleId?: string,
): string {
  return JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: decision,
      permissionDecisionReason: ruleId ? `${reason} (rule: ${ruleId})` : reason,
    },
  });
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
