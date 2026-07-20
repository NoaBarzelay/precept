// The compiled projection: the check cache the interception hot path reads
// (ARCHITECTURE.md sections 5.2, 6.4). A plain-JSON file derived from the
// catalog cards, local disk only, rebuildable. Deliberately lightweight (JSON,
// no YAML, no card parser) so reading it stays within the D1 budget.

import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  writeSync,
} from "node:fs";
import { dirname, join } from "node:path";
import type { CompiledRule } from "../domain/enforce.ts";
import { canDeny, type Entry, isLive } from "../domain/entry.ts";
import { projectionPath } from "../store/paths.ts";

/**
 * Compile live hard rules into the projection. An operational rule denies; a
 * probationary one asks (R1.19-R1.21). Soft entries and knowledge never enter
 * the projection, so the hot path only ever sees blocking checks.
 */
export function compile(entries: readonly Entry[]): CompiledRule[] {
  const out: CompiledRule[] = [];
  for (const e of entries) {
    if (e.tier !== "hard" || e.check === undefined) continue;
    if (!isLive(e)) continue;
    out.push({
      id: e.id,
      check: e.check,
      outcome: canDeny(e) ? "deny" : "ask",
      reason: firstLine(e.content),
    });
  }
  return out;
}

/** Write the projection atomically to local disk. */
export function writeProjection(
  rules: readonly CompiledRule[],
  path: string = projectionPath(),
): void {
  const dir = dirname(path);
  mkdirSync(dir, { recursive: true });
  const tmp = join(dir, `.policies.${process.pid}.tmp`);
  const fd = openSync(tmp, "w");
  try {
    writeSync(fd, JSON.stringify(rules));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(tmp, path);
}

/** Read the projection. Missing or unreadable yields an empty rule set, so the
 * hot path fails open rather than throwing. */
export function readProjection(path: string = projectionPath()): CompiledRule[] {
  if (!existsSync(path)) return [];
  return JSON.parse(readFileSync(path, "utf8")) as CompiledRule[];
}

function firstLine(content: string): string {
  const line = content.split("\n").find((l) => l.trim() !== "");
  return (line ?? content).trim();
}
