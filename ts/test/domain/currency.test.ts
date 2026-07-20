import { expect, test } from "bun:test";
import type { Candidate } from "../../src/domain/candidate.ts";
import { conflictsAmong, expired } from "../../src/domain/currency.ts";
import {
  type Entry,
  entryError,
  isExpired,
  isLive,
  retire,
  SCHEMA_VERSION,
  type Scope,
  supersede,
} from "../../src/domain/entry.ts";

const entry = (over: Partial<Entry> = {}): Entry => ({
  schemaVersion: SCHEMA_VERSION,
  version: 1,
  id: "an-entry",
  kind: "convention",
  scope: { kind: "global" },
  content: "use the envelope helper",
  validity: { validFrom: "2026-07-01", condition: "always" },
  provenance: { signalKind: "instruction" },
  status: "active",
  ...over,
});

test("retire invalidates without deleting and closes valid-time", () => {
  const r = retire(entry(), "2026-07-20");
  expect(r.status).toBe("retired");
  expect(r.validity.validUntil).toBe("2026-07-20");
  expect(r.version).toBe(2); // CAS token bumped
  expect(isLive(r)).toBe(false);
  expect(entryError(r)).toBeNull();
});

test("retire is a no-op on an already-governed entry (safe to repeat)", () => {
  const once = retire(entry(), "2026-07-20");
  expect(retire(once, "2026-07-21")).toBe(once); // unchanged, version not bumped
});

test("supersede records the successor and validates", () => {
  const s = supersede(entry(), "the-newer-entry", "2026-07-20");
  expect(s.status).toBe("superseded");
  expect(s.supersededBy).toBe("the-newer-entry");
  expect(isLive(s)).toBe(false);
  expect(entryError(s)).toBeNull();
});

test("a superseded entry must name its successor; a pointer needs superseded status", () => {
  expect(entryError({ ...entry(), status: "superseded" })).toMatch(/must record supersededBy/);
  expect(entryError({ ...entry(), supersededBy: "x" })).toMatch(/only valid on a superseded/);
});

test("isExpired compares the expiry date to today", () => {
  const dated = entry({ validity: { validFrom: "2026-07-01", condition: "the sprint", validUntil: "2026-07-15" } });
  expect(isExpired(dated, "2026-07-20")).toBe(true);
  expect(isExpired(dated, "2026-07-10")).toBe(false);
  expect(isExpired(entry(), "2026-07-20")).toBe(false); // no expiry set
});

test("expired selects only active, past-expiry entries", () => {
  const past = entry({ id: "past", validity: { validFrom: "2026-07-01", condition: "x", validUntil: "2026-07-10" } });
  const future = entry({ id: "future", validity: { validFrom: "2026-07-01", condition: "x", validUntil: "2026-08-01" } });
  const plain = entry({ id: "plain" });
  const got = expired([past, future, plain], "2026-07-20");
  expect(got.map((e) => e.id)).toEqual(["past"]);
});

const candidate = (kind: Candidate["kind"], scope: Scope): Candidate => ({
  kind,
  scope,
  content: "use the envelope helper",
  condition: "always",
  signalKind: "instruction",
});

test("conflictsAmong flags a live same-kind same-scope entry", () => {
  const existing = entry({ id: "existing" });
  const got = conflictsAmong(candidate("convention", { kind: "global" }), [existing]);
  expect(got.map((e) => e.id)).toEqual(["existing"]);
});

test("conflictsAmong ignores a different kind, a different scope, and a dead entry", () => {
  const otherKind = entry({ id: "k", kind: "knowledge" });
  const otherScope = entry({ id: "s", scope: { kind: "repository", repository: "acme" } });
  const dead = retire(entry({ id: "d" }), "2026-07-20");
  const got = conflictsAmong(candidate("convention", { kind: "global" }), [otherKind, otherScope, dead]);
  expect(got).toHaveLength(0);
});
