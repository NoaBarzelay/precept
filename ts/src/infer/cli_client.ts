// The real inference backend: the Claude Code subscription via `claude -p`
// (DECISIONS.md, the inference-adapter decision). It asks the model to extract
// at most one durable item from an evidence window, or abstain, using the
// host's native structured-output flag, and validates the result before it
// becomes a candidate.
//
// Two hazards it handles. Recursion: a nested `claude -p` would re-fire
// Precept's own hooks (the fork-bomb from the Python history), so it runs with
// `--setting-sources project` (Precept's hooks are user-source, not loaded) and
// sets a sentinel the hook entrypoints no-op under. Untrusted output: the model
// result is validated against a flat schema and dropped on any mismatch.
//
// The subprocess is injected as a `Runner`, so the prompt, schema, and parsing
// are tested offline against a fake; only the real spawn needs a live model.

import type { Candidate } from "../domain/candidate.ts";
import type { Scope } from "../domain/entry.ts";
import type { EvidenceRecord } from "../record/evidence.ts";
import { type InferenceClient, NullClient } from "./client.ts";

/** Runs `claude` with the given args and prompt, returns stdout. */
export type Runner = (args: string[], prompt: string) => Promise<string>;

/** The sentinel a nested Precept process checks to no-op (recursion guard). */
export const SUBPROCESS_SENTINEL = "PRECEPT_INFERENCE_SUBPROCESS";

const MODEL = "claude-haiku-4-5-20251001";

const SYSTEM_PROMPT = `You extract at most one durable item from a short slice of a coding session, for a single developer's personal AI-assistance catalog.

Return abstain=true unless the slice identifies ONE clear item worth remembering across sessions. Prefer abstaining: one-off task chatter, questions, and tool output are not durable.

A "knowledge" item is a fact the work depends on (stack, deploy targets, project facts). A "convention" is a way of working the developer wants followed. State the condition it holds under, even if "always". Scope it to the narrowest of: this repository, a language, a path, or global.`;

// A flat, non-recursive schema (the host's structured output does not allow
// recursion, so the model never emits a check AST; enforcement checks are a
// separate step).
const SCHEMA = {
  type: "object",
  properties: {
    abstain: { type: "boolean" },
    kind: { type: "string", enum: ["knowledge", "convention"] },
    content: { type: "string" },
    condition: { type: "string" },
    scopeKind: { type: "string", enum: ["global", "repository", "language", "path"] },
    scopeValue: { type: "string" },
  },
  required: ["abstain"],
  additionalProperties: false,
};

interface Extracted {
  abstain?: boolean;
  kind?: "knowledge" | "convention";
  content?: string;
  condition?: string;
  scopeKind?: "global" | "repository" | "language" | "path";
  scopeValue?: string;
}

export class CliClient implements InferenceClient {
  constructor(private readonly runner: Runner = spawnClaude) {}

  async propose(evidence: EvidenceRecord): Promise<Candidate | null> {
    const args = [
      "-p",
      "--output-format",
      "json",
      "--json-schema",
      JSON.stringify(SCHEMA),
      "--system-prompt",
      SYSTEM_PROMPT,
      "--setting-sources",
      "project",
      "--model",
      MODEL,
    ];
    let raw: string;
    try {
      raw = await this.runner(args, renderEvidence(evidence));
    } catch {
      return null; // unreachable model: abstain (N1), the loop just learns nothing
    }
    return toCandidate(parseStructured(raw), evidence);
  }
}

function renderEvidence(e: EvidenceRecord): string {
  const parts = [
    `signal: ${e.signalKind}`,
    e.repository !== undefined ? `repository: ${e.repository}` : "",
    "",
    e.turns,
  ];
  if (e.agentOutput !== undefined && e.finalState !== undefined) {
    parts.push("", "agent wrote:", e.agentOutput, "", "final state:", e.finalState);
  }
  return parts.filter((p) => p !== "").join("\n");
}

/** Extract the structured output from the `claude -p --output-format json` envelope. */
export function parseStructured(raw: string): Extracted | null {
  try {
    const env = JSON.parse(raw) as Record<string, unknown>;
    const so =
      (env.structured_output as unknown) ??
      (env.result as unknown) ??
      env;
    return typeof so === "object" && so !== null ? (so as Extracted) : null;
  } catch {
    return null;
  }
}

/** Map a validated extraction to a Candidate, or null to abstain. */
export function toCandidate(
  ex: Extracted | null,
  evidence: EvidenceRecord,
): Candidate | null {
  if (ex === null || ex.abstain === true) return null;
  if (
    (ex.kind !== "knowledge" && ex.kind !== "convention") ||
    typeof ex.content !== "string" ||
    ex.content.trim() === "" ||
    typeof ex.condition !== "string" ||
    ex.condition.trim() === ""
  ) {
    return null; // malformed extraction: treat as abstain rather than guess
  }
  return {
    kind: ex.kind,
    scope: toScope(ex),
    content: ex.content.trim(),
    condition: ex.condition.trim(),
    signalKind: evidence.signalKind,
    evidenceId: evidence.id,
  };
}

function toScope(ex: Extracted): Scope {
  const v = ex.scopeValue?.trim();
  if (ex.scopeKind === "repository" && v) return { kind: "repository", repository: v };
  if (ex.scopeKind === "language" && v) return { kind: "language", language: v };
  if (ex.scopeKind === "path" && v) return { kind: "path", glob: v };
  return { kind: "global" };
}

/**
 * Select the inference backend. `PRECEPT_INFERENCE=cli` uses the real
 * subscription-backed client; anything else abstains rather than pretending to
 * learn. Tests inject a client directly and do not go through here.
 */
export function makeClient(): InferenceClient {
  return process.env.PRECEPT_INFERENCE === "cli" ? new CliClient() : new NullClient();
}

/** The real subprocess. Guards recursion via --setting-sources and the sentinel. */
async function spawnClaude(args: string[], prompt: string): Promise<string> {
  const proc = Bun.spawn(["claude", ...args, prompt], {
    stdout: "pipe",
    stderr: "pipe",
    env: { ...process.env, [SUBPROCESS_SENTINEL]: "1" },
  });
  const out = await new Response(proc.stdout).text();
  await proc.exited;
  return out;
}
