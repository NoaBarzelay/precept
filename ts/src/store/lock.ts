// A cross-process advisory lock for a card's read-modify-write (ARCHITECTURE.md
// section 7: "read-modify-write is locked end to end, not just at the write").
// An O_EXCL lockfile serializes concurrent sessions so two of them cannot each
// read version N and both write N+1. The lock lives in the local state dir,
// never the synced catalog.

import { closeSync, mkdirSync, openSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { stateDir } from "./paths.ts";

function lockPath(id: string): string {
  return join(stateDir(), "locks", `${id}.lock`);
}

/** Run `fn` while holding the card's lock. Spins briefly for a held lock. */
export function withCardLock<T>(id: string, fn: () => T): T {
  const path = lockPath(id);
  mkdirSync(dirname(path), { recursive: true });
  let fd: number | undefined;
  for (let attempt = 0; attempt < 200; attempt++) {
    try {
      fd = openSync(path, "wx"); // O_CREAT | O_EXCL
      break;
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
      Bun.sleepSync(5);
    }
  }
  if (fd === undefined) throw new Error(`could not acquire lock for ${id}`);
  try {
    return fn();
  } finally {
    closeSync(fd);
    try {
      rmSync(path);
    } catch {
      // another holder already cleaned it; ignore
    }
  }
}
