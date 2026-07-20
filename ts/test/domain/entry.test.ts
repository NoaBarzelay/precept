import { expect, test } from "bun:test";
import {
  canDeny,
  type Entry,
  entryError,
  isLive,
  SCHEMA_VERSION,
} from "../../src/domain/entry.ts";

function knowledge(over: Partial<Entry> = {}): Entry {
  return {
    schemaVersion: SCHEMA_VERSION,
    version: 1,
    id: "staging-runs-on-render",
    kind: "knowledge",
    scope: { kind: "repository", repository: "acme-api" },
    content: "Staging runs on Render, prod is Fly.io (app acme-api).",
    validity: { validFrom: "2026-07-19", condition: "always" },
    provenance: { signalKind: "stated-knowledge" },
    status: "active",
    ...over,
  };
}

function hardRule(over: Partial<Entry> = {}): Entry {
  return {
    schemaVersion: SCHEMA_VERSION,
    version: 1,
    id: "uv-not-pip",
    kind: "rule",
    scope: { kind: "repository", repository: "acme-api" },
    content: "In a uv project, use uv, never plain pip.",
    validity: { validFrom: "2026-07-19", condition: "the project uses uv" },
    provenance: { signalKind: "correction" },
    status: "active",
    tier: "hard",
    lifecycle: "operational",
    confirmations: 3,
    check: {
      op: "str.contains",
      field: { kind: "input", key: "command" },
      value: "pip install",
    },
    ...over,
  };
}

test("a valid knowledge entry and a valid hard rule pass", () => {
  expect(entryError(knowledge())).toBeNull();
  expect(entryError(hardRule())).toBeNull();
});

test("a wrong schema version is rejected", () => {
  expect(entryError(knowledge({ schemaVersion: 99 }))).toContain("schemaVersion");
});

test("a condition must be stated even when it is always", () => {
  expect(
    entryError(knowledge({ validity: { validFrom: "2026-07-19", condition: "  " } })),
  ).toContain("condition");
});

test("validFrom must be an ISO date", () => {
  expect(
    entryError(knowledge({ validity: { validFrom: "yesterday", condition: "always" } })),
  ).toContain("ISO date");
});

test("a hard tier requires a well-formed check on a rule", () => {
  expect(entryError(hardRule({ check: undefined }))).toContain("requires a check");
  expect(entryError(hardRule({ kind: "knowledge" }))).toContain("only a rule may be hard");
  expect(
    entryError(hardRule({ check: { op: "str.regex", field: { kind: "tool" }, pattern: "a(b" } })),
  ).not.toBeNull();
});

test("a check without a hard tier is rejected", () => {
  expect(
    entryError(knowledge({ check: { op: "str.eq", field: { kind: "tool" }, value: "Bash" } })),
  ).toContain("only meaningful on a hard rule");
});

test("a probationary rule cannot deny; an operational one can", () => {
  expect(canDeny(hardRule({ lifecycle: "operational" }))).toBe(true);
  expect(canDeny(hardRule({ lifecycle: "probationary", confirmations: 1 }))).toBe(false);
  expect(canDeny(knowledge())).toBe(false);
});

test("retired or expired entries are not live", () => {
  expect(isLive(knowledge())).toBe(true);
  expect(isLive(knowledge({ status: "retired" }))).toBe(false);
  expect(
    isLive(knowledge({ validity: { validFrom: "2026-01-01", validUntil: "2026-06-01", condition: "x" } })),
  ).toBe(false);
});
