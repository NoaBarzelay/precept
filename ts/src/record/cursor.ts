// The per-session observation cursor (ARCHITECTURE.md section 5.4). Each
// SessionEnd drafts evidence only from the transcript entries it has not seen,
// so a re-fired observation (a resumed session ends again) never re-drafts a
// turn. The cursor is the count of entries already consumed. It is derived,
// operational state: local disk only, rebuildable (a lost cursor at worst
// re-drafts, and the write path dedups by evidence id).

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { cursorPath } from "../store/paths.ts";

/** Entries already consumed for this session; 0 when none, unreadable, or bad. */
export function readCursor(sessionId: string): number {
  try {
    const data = JSON.parse(readFileSync(cursorPath(sessionId), "utf8")) as {
      offset?: unknown;
    };
    const n = data.offset;
    return typeof n === "number" && Number.isInteger(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

/** Record how many entries have now been consumed for this session. */
export function writeCursor(sessionId: string, offset: number): void {
  const path = cursorPath(sessionId);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify({ offset: Math.max(0, Math.trunc(offset)) })}\n`);
}

/** Whether a cursor exists for this session (a session already observed). */
export function hasCursor(sessionId: string): boolean {
  return existsSync(cursorPath(sessionId));
}
