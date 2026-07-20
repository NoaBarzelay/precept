// Register (and exactly un-register) Precept's hook entrypoints in Claude
// Code's settings.json (ARCHITECTURE.md section 5.4; N8, one-command override
// with an exact inverse). This is host knowledge: the settings-file shape and
// the hook wire format are the host's, so the adapter that writes them lives
// here beside the event parser. A second host is a second installer.
//
// The registration is deliberately self-marking, not tracked in a sidecar: each
// command Precept writes is prefixed with a `PRECEPT_MANAGED=1` shell
// assignment. That makes every Precept entry identifiable in-place with no
// custom keys the host might reject, so install is idempotent (strip ours, add
// ours) and uninstall removes exactly ours and nothing the user authored. The
// marker is a harmless env assignment; nothing reads it.
//
// Writes go through a temp file, an atomic rename, and a `.bak` of the prior
// settings, so a crash mid-write leaves either the old file or the new one.

import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { claudeSettingsPath } from "../store/paths.ts";

/** The shell marker that identifies a command Precept wrote. */
export const MANAGED_MARKER = "PRECEPT_MANAGED=1";

/** One hook registration: which event, an optional tool matcher, the entrypoint. */
interface HookSpec {
  readonly event: string;
  readonly matcher: string | null;
  readonly entrypoint: string;
}

// The entrypoints and the events each serves (section 5.4). PreToolUse guards
// every tool with the "*" matcher; per-tool narrowing is the policy matcher's
// job, not the hook's, so one registration covers the event. Recording paths
// (PostToolUse, SessionEnd) are always registered: they only append evidence
// and history off the turn, so they cost no model tokens; the spend is at
// `detect`, which is a separate, gated step.
const HOOK_SPECS: readonly HookSpec[] = [
  { event: "PreToolUse", matcher: "*", entrypoint: "interception.ts" },
  { event: "UserPromptSubmit", matcher: null, entrypoint: "injection.ts" },
  { event: "SessionStart", matcher: null, entrypoint: "injection.ts" },
  { event: "PostToolUse", matcher: null, entrypoint: "observation.ts" },
  { event: "SessionEnd", matcher: null, entrypoint: "observation.ts" },
];

interface HookCommand {
  readonly type: "command";
  readonly command: string;
}

interface HookEntry {
  readonly matcher?: string;
  readonly hooks: HookCommand[];
}

type Settings = Record<string, unknown>;

/** The absolute-path command that runs one entrypoint, self-marked. */
function commandFor(runtime: string, srcDir: string, entrypoint: string): string {
  const file = join(srcDir, entrypoint);
  return `${MANAGED_MARKER} "${runtime}" "${file}"`;
}

/** True for a hook entry Precept wrote (any of its commands carries the marker). */
function isManaged(entry: unknown): boolean {
  if (typeof entry !== "object" || entry === null) return false;
  const hooks = (entry as HookEntry).hooks;
  if (!Array.isArray(hooks)) return false;
  return hooks.some(
    (h) =>
      typeof h === "object" &&
      h !== null &&
      typeof (h as HookCommand).command === "string" &&
      (h as HookCommand).command.includes(MANAGED_MARKER),
  );
}

/**
 * Return a copy of settings with every Precept-managed hook entry removed and
 * any event left empty pruned. The exact inverse of {@link applyInstall}'s add.
 */
export function stripManaged(settings: Settings): Settings {
  const out: Settings = { ...settings };
  const hooks = out.hooks;
  if (typeof hooks !== "object" || hooks === null) return out;
  const next: Record<string, unknown> = {};
  for (const [event, entries] of Object.entries(hooks as Record<string, unknown>)) {
    if (!Array.isArray(entries)) {
      next[event] = entries;
      continue;
    }
    const kept = entries.filter((e) => !isManaged(e));
    if (kept.length > 0) next[event] = kept;
  }
  if (Object.keys(next).length > 0) out.hooks = next;
  else delete out.hooks;
  return out;
}

/**
 * Return a copy of settings with Precept's hooks registered. Idempotent: any
 * prior Precept entries are stripped first, so re-running never accumulates
 * duplicates. `runtime` is the absolute path to the JS runtime (bun), `srcDir`
 * the absolute directory holding the entrypoints.
 */
export function applyInstall(
  settings: Settings,
  runtime: string,
  srcDir: string,
): Settings {
  const out = stripManaged(settings);
  const hooks: Record<string, unknown[]> = {};
  // Carry over the user's surviving events.
  if (typeof out.hooks === "object" && out.hooks !== null) {
    for (const [event, entries] of Object.entries(out.hooks as Record<string, unknown>)) {
      hooks[event] = Array.isArray(entries) ? [...entries] : [entries];
    }
  }
  for (const spec of HOOK_SPECS) {
    const entry: HookEntry = {
      ...(spec.matcher !== null ? { matcher: spec.matcher } : {}),
      hooks: [{ type: "command", command: commandFor(runtime, srcDir, spec.entrypoint) }],
    };
    (hooks[spec.event] ??= []).push(entry);
  }
  out.hooks = hooks;
  return out;
}

/** The events Precept registers, for the CLI to report. */
export function registeredEvents(): string[] {
  return [...new Set(HOOK_SPECS.map((s) => s.event))];
}

// --- IO wrappers -----------------------------------------------------------

/** The absolute directory holding the hook entrypoints (the src/ dir). */
function entrypointDir(): string {
  return resolve(import.meta.dir, "..");
}

function loadSettings(path: string): Settings {
  try {
    const data = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return typeof data === "object" && data !== null ? (data as Settings) : {};
  } catch {
    return {}; // missing or unparseable: start clean rather than fail the install
  }
}

/** Write settings atomically, keeping a `.bak` of the prior file. */
function writeSettings(path: string, settings: Settings): void {
  const dir = dirname(path);
  mkdirSync(dir, { recursive: true });
  if (existsSync(path)) writeFileSync(`${path}.bak`, readFileSync(path));
  const tmp = join(dir, `.settings.${process.pid}.tmp`);
  writeFileSync(tmp, `${JSON.stringify(settings, null, 2)}\n`);
  renameSync(tmp, path);
}

/** Register Precept's hooks in Claude Code's settings.json. Returns the path. */
export function install(): string {
  const path = claudeSettingsPath();
  const runtime = process.execPath;
  writeSettings(path, applyInstall(loadSettings(path), runtime, entrypointDir()));
  return path;
}

/** Remove exactly Precept's hooks from settings.json. Returns the path. */
export function uninstall(): string {
  const path = claudeSettingsPath();
  writeSettings(path, stripManaged(loadSettings(path)));
  return path;
}
