// The durable review queue (ARCHITECTURE.md section 6.1: the review queue
// survives the session that created it). A candidate the detector proposes
// waits here until it is kept, dismissed, or corrected. One file per candidate
// so add and remove are cheap and a crash cannot tear the set. Local state
// only, never rebuildable from cards (it is pre-decision), so it is operational
// state, not a projection.

import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import type { Candidate } from "../domain/candidate.ts";
import { pendingDir } from "../store/paths.ts";

export interface Pending {
  readonly id: string;
  readonly enqueuedAt: string;
  readonly candidate: Candidate;
}

function pendingPath(id: string): string {
  return join(pendingDir(), `${id}.json`);
}

let counter = 0;

/** Enqueue a proposed candidate for review. Returns the pending record. */
export function enqueue(candidate: Candidate, at: string = new Date().toISOString()): Pending {
  mkdirSync(pendingDir(), { recursive: true });
  // A short, sortable, collision-resistant id without pulling in a uuid dep.
  const id = `${at.replace(/[^0-9]/g, "").slice(0, 14)}-${(counter++).toString(36)}${process.pid.toString(36)}`;
  const record: Pending = { id, enqueuedAt: at, candidate };
  const tmp = `${pendingPath(id)}.tmp`;
  writeFileSync(tmp, JSON.stringify(record, null, 2));
  renameSync(tmp, pendingPath(id));
  return record;
}

/** Every pending candidate, oldest first. */
export function listPending(): Pending[] {
  const dir = pendingDir();
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")) as Pending)
    .sort((a, b) => a.enqueuedAt.localeCompare(b.enqueuedAt));
}

export function getPending(id: string): Pending | undefined {
  const path = pendingPath(id);
  if (!existsSync(path)) return undefined;
  return JSON.parse(readFileSync(path, "utf8")) as Pending;
}

/** Remove a pending candidate once it has been reviewed. */
export function removePending(id: string): boolean {
  const path = pendingPath(id);
  if (!existsSync(path)) return false;
  rmSync(path);
  return true;
}
