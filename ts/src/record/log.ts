// Append-only JSONL logs (ARCHITECTURE.md section 6.1: evidence is
// append-only and immutable; section 6.5/N6: decisions are an immutable
// record). One writer, appends never conflict, so these are the append-and-
// invalidate spine the design already keeps.

import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

/** Append one record as a JSON line, creating the parent directory. */
export function appendLine(path: string, record: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, `${JSON.stringify(record)}\n`);
}

/** Read all records from a JSONL log; empty if the log does not exist. */
export function readLines<T>(path: string): T[] {
  if (!existsSync(path)) return [];
  const text = readFileSync(path, "utf8");
  const out: T[] = [];
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    out.push(JSON.parse(line) as T);
  }
  return out;
}
