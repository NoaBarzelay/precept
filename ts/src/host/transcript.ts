// Read a finished Claude Code session transcript and draft evidence from it
// (ARCHITECTURE.md sections 5.4 observation, 6.1 signals observed, 6.2 the
// evidence record). This is host knowledge: the transcript's line shape is the
// host's own wire format, so parsing it belongs here beside the hook-event
// parser, and a second host is a second adapter.
//
// Two signals are drafted. A human-typed turn sources an instruction or a
// correction, tagged by cheap cues; its evidence carries a verbatim window of
// the surrounding turns, because intent lives in the exchange around an action,
// not the action alone (R1.1). A file the agent wrote whose on-disk state no
// longer matches what it wrote is a silent edit (R1.1): the draft carries both
// the agent's output and the file's final state so the diff is reconstructable
// later (R1.14). Provenance gates what each can become downstream: only a
// user-typed turn may ever source a blocking entry, and a silent edit, inferred
// from an act the user never remarked on, may steer but never block (6.1).
//
// Parsing is best-effort and total: a malformed line is skipped, never thrown,
// so a single bad entry cannot wedge the observation pass (D2).

import { readFileSync } from "node:fs";
import { basename } from "node:path";
import type { EvidenceRecord } from "../domain/evidence.ts";
import type { SignalKind } from "../domain/entry.ts";

/** One parsed transcript line, narrowed to the fields evidence needs. */
export interface TranscriptEntry {
  readonly role: "user" | "assistant" | "other";
  /** Human/agent-authored text, empty when the entry carries none. */
  readonly text: string;
  /** True only for a genuine user-typed turn (not a tool result, not a subagent). */
  readonly humanTyped: boolean;
  /** Files this entry's tool calls wrote, with what the agent wrote to each. */
  readonly writes: readonly FileWrite[];
  readonly at?: string;
  readonly cwd?: string;
}

export interface FileWrite {
  readonly path: string;
  /** What the agent wrote: a Write's content, or an Edit's replacement text. */
  readonly agentOutput: string;
}

/** Reads a file's final on-disk state; injected so the assembler is testable. */
export type FinalStateReader = (path: string) => string | undefined;

const defaultReader: FinalStateReader = (path) => {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return undefined; // moved, deleted, or unreadable: no silent-edit signal
  }
};

export interface AssembleOptions {
  /** How many entries were already consumed for this session (the cursor). */
  readonly since?: number;
  /** Turns of surrounding context each human-turn window carries. */
  readonly window?: number;
  readonly readFinalState?: FinalStateReader;
}

export interface AssembleResult {
  readonly evidence: readonly EvidenceRecord[];
  /** The number of entries now consumed: the cursor to persist. */
  readonly consumed: number;
}

// Cheap, recall-biased cues that a user turn is a correction rather than a fresh
// instruction. A cost-free tag, not a classification: the detector still judges
// intent from the raw turns. Word-boundary anchored so "another" does not trip
// "no" and "notation" does not trip "not".
const CORRECTION_CUES =
  /\b(no|nope|don'?t|never|not|stop|actually|instead|wrong|should(?:'?ve| have)?|again|undo|revert|isn'?t|aren'?t)\b/i;

const WRITE_TOOLS = new Set(["Write", "Edit", "MultiEdit", "NotebookEdit"]);

interface RawLine {
  readonly type?: unknown;
  readonly message?: unknown;
  readonly isSidechain?: unknown;
  readonly timestamp?: unknown;
  readonly cwd?: unknown;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

/** Parse the transcript JSONL, one narrowed entry per line, skipping junk. */
export function parseTranscript(raw: string): TranscriptEntry[] {
  const out: TranscriptEntry[] = [];
  for (const line of raw.split("\n")) {
    if (line.trim() === "") continue;
    let o: RawLine;
    try {
      o = JSON.parse(line) as RawLine;
    } catch {
      continue; // a torn or partial line: skip, never throw
    }
    out.push(narrow(o));
  }
  return out;
}

function narrow(o: RawLine): TranscriptEntry {
  const type = str(o.type);
  const msg =
    typeof o.message === "object" && o.message !== null
      ? (o.message as Record<string, unknown>)
      : undefined;
  const role = str(msg?.role);
  const at = str(o.timestamp);
  const cwd = str(o.cwd);
  const sidechain = o.isSidechain === true;
  if (type === "user" && role === "user") {
    const { text, isToolResult } = userText(msg?.content);
    return {
      role: "user",
      text,
      // Provenance gate: a real human turn carries text and is neither a tool
      // result nor a subagent's synthesized prompt.
      humanTyped: text !== "" && !isToolResult && !sidechain,
      writes: [],
      ...(at !== undefined ? { at } : {}),
      ...(cwd !== undefined ? { cwd } : {}),
    };
  }
  if (type === "assistant" && role === "assistant") {
    const content = msg?.content;
    return {
      role: "assistant",
      text: assistantText(content),
      humanTyped: false,
      writes: fileWrites(content),
      ...(at !== undefined ? { at } : {}),
      ...(cwd !== undefined ? { cwd } : {}),
    };
  }
  return { role: "other", text: "", humanTyped: false, writes: [] };
}

/** A user turn's text, and whether it is a tool-result turn (not human-typed). */
function userText(content: unknown): { text: string; isToolResult: boolean } {
  if (typeof content === "string") return { text: content.trim(), isToolResult: false };
  if (!Array.isArray(content)) return { text: "", isToolResult: false };
  let isToolResult = false;
  const parts: string[] = [];
  for (const b of content) {
    if (typeof b !== "object" || b === null) continue;
    const block = b as Record<string, unknown>;
    if (block.type === "tool_result") isToolResult = true;
    else if (block.type === "text") {
      const t = str(block.text);
      if (t) parts.push(t);
    }
  }
  return { text: parts.join(" ").trim(), isToolResult };
}

/** The assistant's prose (its `text` blocks only; thinking is excluded to bound size). */
function assistantText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const b of content) {
    if (typeof b !== "object" || b === null) continue;
    const block = b as Record<string, unknown>;
    if (block.type === "text") {
      const t = str(block.text);
      if (t) parts.push(t);
    }
  }
  return parts.join(" ").trim();
}

/** The files a turn's tool calls wrote, with the text the agent wrote to each. */
function fileWrites(content: unknown): FileWrite[] {
  if (!Array.isArray(content)) return [];
  const out: FileWrite[] = [];
  for (const b of content) {
    if (typeof b !== "object" || b === null) continue;
    const block = b as Record<string, unknown>;
    if (block.type !== "tool_use") continue;
    const name = str(block.name);
    if (name === undefined || !WRITE_TOOLS.has(name)) continue;
    const input =
      typeof block.input === "object" && block.input !== null
        ? (block.input as Record<string, unknown>)
        : {};
    const path = str(input.file_path) ?? str(input.notebook_path) ?? str(input.path);
    if (path === undefined) continue;
    const agentOutput = str(input.content) ?? str(input.new_string) ?? str(input.new_source);
    if (agentOutput === undefined) continue;
    out.push({ path, agentOutput });
  }
  return out;
}

function renderTurn(e: TranscriptEntry): string {
  const who = e.role === "user" ? "user" : "assistant";
  return `${who}: ${e.text}`;
}

/**
 * Draft evidence from a transcript. Processes only entries at or after `since`
 * (the per-session cursor), so a re-fired observation never re-drafts a turn.
 * Human turns become instruction/correction evidence with a verbatim window of
 * surrounding turns; a file whose disk state diverges from the last thing the
 * agent wrote to it becomes a silent-edit draft.
 */
export function assembleEvidence(
  raw: string,
  meta: { session: string; repository?: string },
  options: AssembleOptions = {},
): AssembleResult {
  const entries = parseTranscript(raw);
  const window = options.window ?? 6;
  const readFinalState = options.readFinalState ?? defaultReader;
  // A cursor past the end means the transcript was rotated or truncated: start
  // over rather than skip everything.
  const since = options.since !== undefined && options.since <= entries.length
    ? options.since
    : 0;
  const evidence: EvidenceRecord[] = [];

  for (let i = since; i < entries.length; i++) {
    const e = entries[i]!;
    if (!e.humanTyped) continue;
    const start = Math.max(0, i - window);
    const turns = entries
      .slice(start, i + 1)
      .filter((t) => t.text !== "")
      .map(renderTurn)
      .join("\n---\n");
    const signalKind: SignalKind = CORRECTION_CUES.test(e.text)
      ? "correction"
      : "instruction";
    evidence.push({
      id: `${meta.session}:turn:${i}`,
      at: e.at ?? "",
      signalKind,
      turns,
      session: meta.session,
      ...(repoOf(e, meta.repository) !== undefined
        ? { repository: repoOf(e, meta.repository)! }
        : {}),
    });
  }

  // Silent edits: the LAST thing the agent wrote to each path is its final
  // output; compare that to the file's disk state. Only paths written at or
  // after the cursor are considered, so a prior session's writes are not
  // re-diffed. A missing or unchanged file yields no signal.
  const lastWrite = new Map<string, { write: FileWrite; index: number }>();
  for (let i = since; i < entries.length; i++) {
    for (const w of entries[i]!.writes) lastWrite.set(w.path, { write: w, index: i });
  }
  for (const [path, { write, index }] of lastWrite) {
    const finalState = readFinalState(path);
    if (finalState === undefined || finalState === write.agentOutput) continue;
    const e = entries[index]!;
    const start = Math.max(0, index - window);
    const turns = entries
      .slice(start, index + 1)
      .filter((t) => t.text !== "")
      .map(renderTurn)
      .join("\n---\n");
    evidence.push({
      id: `${meta.session}:edit:${basename(path)}:${index}`,
      at: e.at ?? "",
      signalKind: "silent-edit",
      turns,
      session: meta.session,
      agentOutput: write.agentOutput,
      finalState,
      ...(repoOf(e, meta.repository) !== undefined
        ? { repository: repoOf(e, meta.repository)! }
        : {}),
    });
  }

  return { evidence, consumed: entries.length };
}

/** Repository hint: the caller's, else the entry's cwd basename. No fs read. */
function repoOf(e: TranscriptEntry, fallback?: string): string | undefined {
  if (fallback !== undefined) return fallback;
  return e.cwd !== undefined ? basename(e.cwd) : undefined;
}

/**
 * Read a transcript file and draft evidence from it. An unreadable path yields
 * no evidence and leaves the cursor where it was (fail-open, D2), so a missing
 * transcript never wedges the observation pass.
 */
export function ingestTranscriptFile(
  path: string,
  meta: { session: string; repository?: string },
  options: AssembleOptions = {},
): AssembleResult {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    return { evidence: [], consumed: options.since ?? 0 };
  }
  return assembleEvidence(raw, meta, options);
}
