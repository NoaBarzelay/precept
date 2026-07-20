// The human review gate (ARCHITECTURE.md sections 6.1, 6.6, D5, N7). Every
// candidate is kept, dismissed, or corrected, and the outcome is an immutable
// decision record. Nothing reaches the catalog except through here, which is
// what makes approval a structural property rather than a step.

import { existsSync } from "node:fs";
import { randomUUID } from "node:crypto";
import type { Candidate } from "../domain/candidate.ts";
import {
  type Entry,
  type SignalKind,
  SCHEMA_VERSION,
} from "../domain/entry.ts";
import {
  type DecisionRecord,
  appendDecision,
  deltaBetween,
} from "../record/decision.ts";
import { Index } from "../retrieve/index.ts";
import { writeCard } from "../store/card.ts";
import { cardPath } from "../store/paths.ts";

export type Review =
  | { readonly action: "keep" }
  | { readonly action: "dismiss"; readonly reason: string }
  | { readonly action: "correct"; readonly corrected: Candidate };

export interface ReviewOptions {
  /** Override the valid-from date (ISO), for deterministic tests. */
  now?: string;
  /** Override the decision timestamp (ISO). */
  at?: string;
  /** Override the decision id. */
  decisionId?: string;
}

export interface ReviewResult {
  readonly decision: DecisionRecord;
  /** The committed entry, present on keep and correct. */
  readonly entry?: Entry;
}

// Only a user-typed turn may source a blocking entry (ARCHITECTURE 6.1). An
// implicit signal can steer but never block.
const USER_TYPED: readonly SignalKind[] = [
  "instruction",
  "correction",
  "stated-knowledge",
];

/** Apply a reviewer's decision to a proposed candidate, committing on keep or correct. */
export function review(
  proposed: Candidate,
  decision: Review,
  opts: ReviewOptions = {},
): ReviewResult {
  const at = opts.at ?? new Date().toISOString();
  const now = opts.now ?? at.slice(0, 10);
  const decisionId = opts.decisionId ?? randomUUID();

  if (decision.action === "dismiss") {
    const record: DecisionRecord = {
      id: decisionId,
      at,
      action: "dismiss",
      proposed,
      reason: decision.reason,
      ...(proposed.evidenceId !== undefined
        ? { evidenceId: proposed.evidenceId }
        : {}),
    };
    appendDecision(record);
    return { decision: record };
  }

  const chosen =
    decision.action === "correct" ? decision.corrected : proposed;
  const committed = applyProvenanceGate(chosen);
  const entry = toEntry(committed, now, decisionId);

  writeCard(entry);
  const index = new Index();
  try {
    index.upsert(entry);
  } finally {
    index.close();
  }

  const delta = deltaBetween(proposed, committed);
  const record: DecisionRecord = {
    id: decisionId,
    at,
    action: decision.action,
    proposed,
    entryId: entry.id,
    ...(delta.changed.length > 0 ? { delta } : {}),
    ...(proposed.evidenceId !== undefined
      ? { evidenceId: proposed.evidenceId }
      : {}),
  };
  appendDecision(record);
  return { decision: record, entry };
}

/** Downgrade a hard candidate that an implicit signal is not allowed to source. */
export function applyProvenanceGate(candidate: Candidate): Candidate {
  if (candidate.tier === "hard" && !USER_TYPED.includes(candidate.signalKind)) {
    const { check: _check, ...rest } = candidate;
    return { ...rest, tier: "soft" };
  }
  return candidate;
}

function toEntry(candidate: Candidate, now: string, decisionId: string): Entry {
  const id = uniqueId(slugify(candidate.content));
  const base: Entry = {
    schemaVersion: SCHEMA_VERSION,
    id,
    kind: candidate.kind,
    scope: candidate.scope,
    content: candidate.content,
    validity: { validFrom: now, condition: candidate.condition },
    provenance: {
      signalKind: candidate.signalKind,
      decisionId,
      ...(candidate.quote !== undefined ? { quote: candidate.quote } : {}),
    },
    status: "active",
  };
  if (candidate.tier === "hard" && candidate.check !== undefined) {
    // Enters enforcement probationary; it may never deny until it graduates.
    return {
      ...base,
      tier: "hard",
      check: candidate.check,
      lifecycle: "probationary",
      confirmations: 0,
    };
  }
  if (candidate.tier === "soft") {
    return { ...base, tier: "soft" };
  }
  return base;
}

function slugify(content: string): string {
  const base = content
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .split("-")
    .filter((w) => w !== "")
    .slice(0, 6)
    .join("-");
  return base === "" ? "entry" : base;
}

function uniqueId(base: string): string {
  if (!existsSync(cardPath(base))) return base;
  for (let n = 2; ; n++) {
    const candidate = `${base}-${n}`;
    if (!existsSync(cardPath(candidate))) return candidate;
  }
}
