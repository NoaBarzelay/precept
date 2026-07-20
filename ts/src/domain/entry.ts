// The entry model: what Precept records and governs (ARCHITECTURE.md sections
// 5.2, 6.1, 7). One entry is one catalog card. This module is the typed
// contract the card frontmatter must satisfy; it is pure and imports no I/O, so
// `domain` stays a leaf.

import { type Check, checkError } from "./check.ts";

/** The frontmatter schema version. Stamped on every card (N12). */
export const SCHEMA_VERSION = 1;

/**
 * The nine planned entity types. Knowledge-first delivery builds `knowledge`,
 * `rule`, and `convention` first (ARCHITECTURE section 10); the rest are named
 * so the type is closed and the router has a target set.
 */
export type EntryKind =
  | "knowledge"
  | "rule"
  | "convention"
  | "skill"
  | "agent"
  | "output-style"
  | "command"
  | "mcp"
  | "permission";

export const ENTRY_KINDS: readonly EntryKind[] = [
  "knowledge",
  "rule",
  "convention",
  "skill",
  "agent",
  "output-style",
  "command",
  "mcp",
  "permission",
];

/** Where an entry applies. Its recorded condition, in structured form. */
export type Scope =
  | { readonly kind: "global" }
  | { readonly kind: "repository"; readonly repository: string }
  | { readonly kind: "language"; readonly language: string }
  | { readonly kind: "path"; readonly glob: string }
  | { readonly kind: "situation"; readonly name: string };

/**
 * Bi-temporal validity, split across the card and git (ARCHITECTURE section 7).
 * Valid-time lives here; transaction-time is the card's git history. `condition`
 * is stated even when the answer is "always" (R1.3, R2.3).
 */
export interface Validity {
  /** ISO date the preference or fact began to hold. */
  readonly validFrom: string;
  /** ISO date its condition stopped holding, if it has. */
  readonly validUntil?: string;
  /** The condition it holds under, stated even when "always". */
  readonly condition: string;
}

export type SignalKind =
  | "instruction"
  | "correction"
  | "repeated-choice"
  | "silent-edit"
  | "stated-knowledge"
  | "agent-research";

/**
 * The evidence an entry was drawn from (N6). For an implicit signal there may
 * be no quote; the diff or the recurrence stands in.
 */
export interface Provenance {
  readonly signalKind: SignalKind;
  /** The decision record this entry was committed through. */
  readonly decisionId?: string;
  /** The evidence span, verbatim where one exists. */
  readonly quote?: string;
}

/** active until retired or superseded; currency is invalidate-not-delete. */
export type EntryStatus = "active" | "retired" | "superseded";

/** Steer (soft) or block (hard). Only a rule with a check can be hard. */
export type EnforcementTier = "soft" | "hard";

/**
 * A hard rule is confirmed in practice before it enforces (R1.19-R1.21): it is
 * probationary until a threshold of confirmations, then operational.
 */
export type LifecycleState = "probationary" | "operational";

export interface Entry {
  readonly schemaVersion: number;
  /**
   * The per-card revision, bumped on every write. It is the compare-and-swap
   * token the write model uses to detect a concurrent clobber (ARCHITECTURE
   * section 7), including the Python runtime writing the same card during the
   * strangler. Distinct from schemaVersion, which is the format version.
   */
  readonly version: number;
  readonly id: string;
  readonly kind: EntryKind;
  readonly scope: Scope;
  /** The card body: the preference, fact, or research content. */
  readonly content: string;
  readonly validity: Validity;
  readonly provenance: Provenance;
  readonly status: EntryStatus;
  /** Enforcement, present only when the entry blocks. */
  readonly tier?: EnforcementTier;
  /** The compiled check, required when tier is "hard". */
  readonly check?: Check;
  readonly lifecycle?: LifecycleState;
  /** Consecutive confirmations while probationary. */
  readonly confirmations?: number;
}

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;

/**
 * Structural validation of an entry against the typed contract. Returns null if
 * valid, else the first problem. This is the frontmatter contract enforced on
 * every read and write (ARCHITECTURE section 7). It does not check host
 * placement rules (a `host` concern) or history (a `gate` concern).
 */
export function entryError(entry: Entry): string | null {
  if (entry.schemaVersion !== SCHEMA_VERSION) {
    return `schemaVersion ${entry.schemaVersion} != ${SCHEMA_VERSION}`;
  }
  if (!Number.isInteger(entry.version) || entry.version < 1) {
    return `version must be a positive integer, got ${entry.version}`;
  }
  if (!ID_RE.test(entry.id)) return `invalid id '${entry.id}'`;
  if (!ENTRY_KINDS.includes(entry.kind)) return `unknown kind '${entry.kind}'`;
  if (entry.validity.condition.trim() === "") return "condition is empty";
  if (!isoDate(entry.validity.validFrom)) {
    return `validFrom '${entry.validity.validFrom}' is not an ISO date`;
  }
  if (
    entry.validity.validUntil !== undefined &&
    !isoDate(entry.validity.validUntil)
  ) {
    return `validUntil '${entry.validity.validUntil}' is not an ISO date`;
  }
  if (entry.content.trim() === "") return "content is empty";

  const scopeErr = scopeError(entry.scope);
  if (scopeErr !== null) return scopeErr;

  // Enforcement invariants (N5: an entry never claims enforcement it cannot
  // deliver). A hard tier requires a well-formed check; probation and
  // confirmations only make sense for a hard rule.
  if (entry.tier === "hard") {
    if (entry.check === undefined) return "hard tier requires a check";
    const cErr = checkError(entry.check);
    if (cErr !== null) return cErr;
    if (entry.kind !== "rule") return "only a rule may be hard";
  }
  if (entry.check !== undefined && entry.tier !== "hard") {
    return "a check is only meaningful on a hard rule";
  }
  if (entry.lifecycle !== undefined && entry.tier !== "hard") {
    return "lifecycle only applies to a hard rule";
  }
  if (entry.confirmations !== undefined && entry.confirmations < 0) {
    return "confirmations cannot be negative";
  }
  return null;
}

function scopeError(scope: Scope): string | null {
  switch (scope.kind) {
    case "global":
      return null;
    case "repository":
      return scope.repository.trim() === "" ? "empty repository scope" : null;
    case "language":
      return scope.language.trim() === "" ? "empty language scope" : null;
    case "path":
      return scope.glob.trim() === "" ? "empty path scope" : null;
    case "situation":
      return scope.name.trim() === "" ? "empty situation scope" : null;
    default:
      return `unknown scope kind '${(scope as { kind: string }).kind}'`;
  }
}

function isoDate(s: string): boolean {
  // YYYY-MM-DD, optionally with a time; must parse to a real date.
  if (!/^\d{4}-\d{2}-\d{2}([T ].*)?$/.test(s)) return false;
  return !Number.isNaN(Date.parse(s));
}

/** The confirmations a probationary rule needs before it graduates (R1.21). */
export const GRADUATION_THRESHOLD = 3;

/**
 * Record one confirmation that a probationary rule's enforcement was intended
 * (R1.21). At the threshold it graduates to operational. Bumps the version (the
 * CAS token). A no-op on a rule that is not a probationary hard rule, which is
 * what makes a double confirmation from two sessions safe. Pure.
 */
export function confirmOnce(
  entry: Entry,
  threshold: number = GRADUATION_THRESHOLD,
): Entry {
  if (entry.tier !== "hard" || entry.lifecycle !== "probationary") return entry;
  const confirmations = (entry.confirmations ?? 0) + 1;
  const graduated = confirmations >= threshold;
  return {
    ...entry,
    version: entry.version + 1,
    confirmations,
    ...(graduated ? { lifecycle: "operational" as const } : {}),
  };
}

/**
 * The user says a probationary rule's enforcement was not intended (R1.20):
 * narrow its recorded condition and reset the confirmation count, so it stays
 * probationary under the tighter condition. Pure.
 */
export function narrowOnReject(entry: Entry, condition?: string): Entry {
  if (entry.tier !== "hard") return entry;
  return {
    ...entry,
    version: entry.version + 1,
    confirmations: 0,
    ...(condition !== undefined
      ? { validity: { ...entry.validity, condition } }
      : {}),
  };
}

/** A probationary hard rule may never emit a deny (fitness function R1.19-R1.21). */
export function canDeny(entry: Entry): boolean {
  return (
    entry.status === "active" &&
    entry.tier === "hard" &&
    entry.lifecycle === "operational"
  );
}

/** Whether an entry is live for retrieval or enforcement (R2.8: exclude stale). */
export function isLive(entry: Entry): boolean {
  return entry.status === "active" && entry.validity.validUntil === undefined;
}
