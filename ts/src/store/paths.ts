// Path resolution and the local-first split (ARCHITECTURE.md section 7, and
// the Storage section of DECISIONS.md).
//
// The catalog (source of truth, markdown cards) may sit in a cloud-synced
// folder. The derived state (SQLite index, operational databases) must not,
// because SQLite corrupts under cloud sync. Both roots are env-overridable so
// tests are hermetic and read no real machine state.

import { homedir } from "node:os";
import { join } from "node:path";

/** The catalog root: markdown cards, the source of truth. May be synced. */
export function catalogDir(): string {
  return process.env.PRECEPT_HOME ?? join(homedir(), ".precept");
}

/** The directory holding entry cards. */
export function entriesDir(): string {
  return join(catalogDir(), "entries");
}

/** Absolute path of one entry card. */
export function cardPath(id: string): string {
  return join(entriesDir(), `${id}.md`);
}

/**
 * The derived-state root: SQLite index and operational databases. Local disk
 * only, never a synced folder.
 */
export function stateDir(): string {
  if (process.env.PRECEPT_STATE_DIR) return process.env.PRECEPT_STATE_DIR;
  const base =
    process.env.XDG_STATE_HOME ?? join(homedir(), ".local", "state");
  return join(base, "precept");
}

/** The derived FTS index database (rebuildable projection). */
export function indexDbPath(): string {
  return join(stateDir(), "index.db");
}

/** The append-only evidence log (operational state). */
export function evidenceLogPath(): string {
  return join(stateDir(), "evidence.jsonl");
}

/** The append-only decision-record log (operational state, N6). */
export function decisionsLogPath(): string {
  return join(stateDir(), "decisions.jsonl");
}
