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

/**
 * Claude Code's own config directory, where `install` registers the hooks.
 * Env-overridable so a test never touches the real one.
 */
export function claudeHome(): string {
  return process.env.PRECEPT_CLAUDE_HOME ?? join(homedir(), ".claude");
}

/** Claude Code's settings file: the install target. */
export function claudeSettingsPath(): string {
  return join(claudeHome(), "settings.json");
}

/**
 * The Obsidian vault root, where knowledge entries live as notes (split-by-kind
 * placement). Unset means no vault is configured and knowledge stays a card
 * under the catalog root, so the system still runs on a machine without one.
 */
export function vaultDir(): string | undefined {
  const dir = process.env.PRECEPT_VAULT;
  return dir === undefined || dir.trim() === "" ? undefined : dir;
}

/**
 * The id-to-path map for vault notes. A note lives in a subject folder under a
 * human title, not at a path derived from its id, so reading one back by id
 * needs a map. Derived and rebuildable by scanning the vault for notes carrying
 * a `precept:` block, so losing it costs a rescan, not data.
 */
export function vaultMapPath(): string {
  return join(stateDir(), "vault-notes.json");
}

/** The derived FTS index database (rebuildable projection). */
export function indexDbPath(): string {
  return join(stateDir(), "index.db");
}

/** The compiled check cache the interception hot path reads (JSON, rebuildable). */
export function projectionPath(): string {
  return join(stateDir(), "policies.json");
}

/**
 * Manifest of the vault notes in the index: path to size and mtime. Lets a
 * refresh re-read only what changed instead of rebuilding 13MB every time.
 * Derived and rebuildable; deleting it costs one full rebuild.
 */
export function vaultManifestPath(): string {
  return join(stateDir(), "vault-index.json");
}

/** Stamp recording when the background vault refresh last ran. */
export function refreshStampPath(): string {
  return join(stateDir(), "vault-refresh.stamp");
}

/** The append-only evidence log (operational state). */
export function evidenceLogPath(): string {
  return join(stateDir(), "evidence.jsonl");
}

/** The append-only ledger of evidence already sent to the model, so detection
 * never pays for the same window twice. */
export function proposedLogPath(): string {
  return join(stateDir(), "proposed.jsonl");
}

/** The append-only decision-record log (operational state, N6). */
export function decisionsLogPath(): string {
  return join(stateDir(), "decisions.jsonl");
}

/** The append-only fault log: what failed open, so a break is not silent (N1). */
export function faultsLogPath(): string {
  return join(stateDir(), "faults.jsonl");
}

/** The append-only tool-call history: the traffic checks are validated against. */
export function historyLogPath(): string {
  return join(stateDir(), "history.jsonl");
}

/** Stamp recording when the session-start backlog prompt last fired, so a
 * queue the user is not clearing does not re-ask every session. */
export function backlogStampPath(): string {
  return join(stateDir(), "backlog-prompt.stamp");
}

/** The durable review queue: one file per candidate awaiting review. */
export function pendingDir(): string {
  return join(stateDir(), "pending");
}
