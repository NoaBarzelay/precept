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
  /**
   * `full` when the agent wrote the whole file (a `Write`); `fragment` when it
   * authored snippets within it (an `Edit`/`MultiEdit`/`NotebookEdit`). The two
   * are diffed against the final file differently: a full write by equality, a
   * fragment by whether it still appears in the file.
   */
  readonly kind: "full" | "fragment";
  /** full: the one whole-file content. fragment: each snippet the agent wrote. */
  readonly outputs: readonly string[];
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
  /** Turns of surrounding context each human-turn window carries. */
  readonly window?: number;
  readonly readFinalState?: FinalStateReader;
}

// Cheap, recall-biased cues that a user turn is a correction rather than a fresh
// instruction. A cost-free tag, not a classification: the detector still judges
// intent from the raw turns. Word-boundary anchored so "another" does not trip
// "no" and "notation" does not trip "not".
const CORRECTION_CUES =
  /\b(no|nope|don'?t|never|not|stop|actually|instead|wrong|should(?:'?ve| have)?|again|undo|revert|isn'?t|aren'?t)\b/i;

// The evidence log is append-only and unbounded, so a single generated file
// must not blow it up. Stored turns and silent-edit payloads are capped; the
// cap is generous (a real correction or diff is far smaller) and a truncation
// marker keeps the record honest for the R1.14 hindsight pass.
const MAX_STORED = 20_000;

function cap(s: string): string {
  return s.length <= MAX_STORED ? s : `${s.slice(0, MAX_STORED)}\n[...truncated]`;
}

// A stable, position-independent FNV-1a hash. Evidence ids are content-derived,
// not index-derived, so a rotated or compacted transcript re-processed from the
// start yields the SAME id for an unchanged observation (deduped) and a fresh id
// for a genuinely new one (recorded). The cursor is then a pure optimisation;
// dedup by id is the correctness guarantee for idempotency.
function hash(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

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
  // Key on the message's own role, not the entry's `type`. The host contract is
  // unversioned and has moved before (constraint 2); a stricter narrowing would
  // fail toward dropping a real turn rather than toward capture. The entry may
  // carry the message inline, so fall back to the entry itself.
  const msg =
    typeof o.message === "object" && o.message !== null
      ? (o.message as Record<string, unknown>)
      : (o as unknown as Record<string, unknown>);
  const role = str(msg.role);
  const at = str(o.timestamp);
  const cwd = str(o.cwd);
  const sidechain = o.isSidechain === true;
  if (role === "user") {
    const { text, isToolResult } = userText(msg.content);
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
  if (role === "assistant") {
    const content = msg.content;
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

/** The files a turn's tool calls wrote, tagged full (whole file) or fragment. */
function fileWrites(content: unknown): FileWrite[] {
  if (!Array.isArray(content)) return [];
  const out: FileWrite[] = [];
  for (const b of content) {
    if (typeof b !== "object" || b === null) continue;
    const block = b as Record<string, unknown>;
    if (block.type !== "tool_use") continue;
    const name = str(block.name);
    if (name === undefined) continue;
    const input =
      typeof block.input === "object" && block.input !== null
        ? (block.input as Record<string, unknown>)
        : {};
    const path = str(input.file_path) ?? str(input.notebook_path) ?? str(input.path);
    if (path === undefined) continue;
    if (name === "Write") {
      const whole = str(input.content);
      if (whole !== undefined) out.push({ path, kind: "full", outputs: [whole] });
    } else if (name === "Edit") {
      const frag = str(input.new_string);
      if (frag !== undefined) out.push({ path, kind: "fragment", outputs: [frag] });
    } else if (name === "NotebookEdit") {
      const frag = str(input.new_source);
      if (frag !== undefined) out.push({ path, kind: "fragment", outputs: [frag] });
    } else if (name === "MultiEdit") {
      // A sequence of replacements; each new_string is a fragment authored into
      // the file. Recorded together so the divergence test sees every one.
      const edits = Array.isArray(input.edits) ? input.edits : [];
      const outputs: string[] = [];
      for (const e of edits) {
        if (typeof e !== "object" || e === null) continue;
        const frag = str((e as Record<string, unknown>).new_string);
        if (frag !== undefined) outputs.push(frag);
      }
      if (outputs.length > 0) out.push({ path, kind: "fragment", outputs });
    }
  }
  return out;
}

/**
 * Whether the file's final state diverges from what the agent wrote. A full
 * write diverges by inequality; a fragment write diverges when any snippet the
 * agent authored is no longer present, meaning the user removed or rewrote it.
 */
function diverged(write: FileWrite, finalState: string): boolean {
  if (write.kind === "full") return finalState !== (write.outputs[0] ?? "");
  return write.outputs.some((o) => o !== "" && !finalState.includes(o));
}

/** The agent's output as one string for the evidence record. */
function joinOutputs(write: FileWrite): string {
  return write.kind === "full"
    ? (write.outputs[0] ?? "")
    : write.outputs.join("\n---\n");
}

function renderTurn(e: TranscriptEntry): string {
  const who = e.role === "user" ? "user" : "assistant";
  return `${who}: ${e.text}`;
}

/**
 * Draft evidence from a transcript. Human turns become instruction/correction
 * evidence with a verbatim window of surrounding turns; a file whose disk state
 * diverges from the last thing the agent wrote to it becomes a silent-edit
 * draft. Ids are content-derived, so re-processing the whole transcript re-emits
 * the same id for an unchanged observation: the caller dedups by id, which makes
 * re-processing idempotent without a cursor (least power, and robust to a
 * compacted or rotated transcript whose indices shift).
 */
export function assembleEvidence(
  raw: string,
  meta: { session: string; repository?: string },
  options: AssembleOptions = {},
): readonly EvidenceRecord[] {
  const entries = parseTranscript(raw);
  const window = options.window ?? 6;
  const readFinalState = options.readFinalState ?? defaultReader;
  const evidence: EvidenceRecord[] = [];

  for (let i = 0; i < entries.length; i++) {
    const e = entries[i]!;
    if (!e.humanTyped) continue;
    const turns = windowAt(entries, i, window);
    const signalKind: SignalKind = CORRECTION_CUES.test(e.text)
      ? "correction"
      : "instruction";
    const repository = repoOf(e, meta.repository);
    evidence.push({
      // Content-derived id: a re-processed transcript re-yields the same id for
      // an unchanged turn (deduped) and a fresh one for a genuinely new turn.
      id: `${meta.session}:turn:${hash(turns)}`,
      at: e.at ?? "",
      signalKind,
      turns,
      session: meta.session,
      ...(repository !== undefined ? { repository } : {}),
    });
  }

  // Silent edits: the LAST thing the agent wrote to each path is its final
  // output; compare that to the file's disk state (R1.1). A missing file, or one
  // that still matches, yields no signal.
  const lastWrite = new Map<string, { write: FileWrite; index: number }>();
  for (let i = 0; i < entries.length; i++) {
    for (const w of entries[i]!.writes) lastWrite.set(w.path, { write: w, index: i });
  }
  for (const [path, { write, index }] of lastWrite) {
    const finalState = readFinalState(path);
    if (finalState === undefined || !diverged(write, finalState)) continue;
    const e = entries[index]!;
    const turns = windowAt(entries, index, window);
    const agentOutput = cap(joinOutputs(write));
    const capped = cap(finalState);
    const repository = repoOf(e, meta.repository);
    evidence.push({
      // The path and content go into the id, so same-basename files never
      // collide and an unchanged edit re-yields the same id.
      id: `${meta.session}:edit:${hash(`${path} ${agentOutput} ${capped}`)}`,
      at: e.at ?? "",
      signalKind: "silent-edit",
      turns,
      session: meta.session,
      agentOutput,
      finalState: capped,
      ...(repository !== undefined ? { repository } : {}),
    });
  }

  return evidence;
}

/** The verbatim window of surrounding turns ending at entry `i`, capped. */
function windowAt(entries: TranscriptEntry[], i: number, window: number): string {
  const turns = entries
    .slice(Math.max(0, i - window), i + 1)
    .filter((t) => t.text !== "")
    .map(renderTurn)
    .join("\n---\n");
  return cap(turns);
}

/** Repository hint: the caller's, else the entry's cwd basename. No fs read. */
function repoOf(e: TranscriptEntry, fallback?: string): string | undefined {
  if (fallback !== undefined) return fallback;
  return e.cwd !== undefined ? basename(e.cwd) : undefined;
}

/**
 * Read a transcript file and draft evidence from it. An unreadable path yields
 * no evidence (fail-open, D2), so a missing transcript never wedges the
 * observation pass.
 */
export function ingestTranscriptFile(
  path: string,
  meta: { session: string; repository?: string },
  options: AssembleOptions = {},
): readonly EvidenceRecord[] {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    return [];
  }
  return assembleEvidence(raw, meta, options);
}
