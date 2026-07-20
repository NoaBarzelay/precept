import { expect, test } from "bun:test";
import {
  canDeny,
  confirmOnce,
  type Entry,
  narrowOnReject,
  SCHEMA_VERSION,
} from "../../src/domain/entry.ts";

function probationary(over: Partial<Entry> = {}): Entry {
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
    lifecycle: "probationary",
    confirmations: 0,
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
    ...over,
  };
}

test("three confirmations graduate a probationary rule", () => {
  let e = probationary();
  expect(canDeny(e)).toBe(false);
  e = confirmOnce(e);
  expect(e.confirmations).toBe(1);
  expect(e.lifecycle).toBe("probationary");
  expect(canDeny(e)).toBe(false);
  e = confirmOnce(e);
  expect(e.lifecycle).toBe("probationary");
  e = confirmOnce(e);
  expect(e.confirmations).toBe(3);
  expect(e.lifecycle).toBe("operational");
  expect(canDeny(e)).toBe(true);
});

test("each confirmation bumps the version (the CAS token)", () => {
  const e0 = probationary();
  const e1 = confirmOnce(e0);
  expect(e1.version).toBe(e0.version + 1);
});

test("confirming an operational rule is a no-op, so a double confirm is safe", () => {
  const op = probationary({ lifecycle: "operational", confirmations: 3 });
  const again = confirmOnce(op);
  expect(again).toBe(op); // same reference, unchanged
  expect(again.confirmations).toBe(3);
});

test("confirmOnce ignores a non-hard or non-probationary entry", () => {
  const knowledge = probationary({ tier: undefined, lifecycle: undefined, check: undefined, kind: "knowledge" });
  expect(confirmOnce(knowledge)).toBe(knowledge);
});

test("reject narrows the condition and resets the count", () => {
  const e = probationary({ confirmations: 2 });
  const r = narrowOnReject(e, "the project uses uv and is not a scratch repo");
  expect(r.confirmations).toBe(0);
  expect(r.validity.condition).toBe("the project uses uv and is not a scratch repo");
  expect(r.lifecycle).toBe("probationary");
  expect(r.version).toBe(e.version + 1);
});

test("a custom threshold graduates sooner", () => {
  let e = probationary();
  e = confirmOnce(e, 1);
  expect(e.lifecycle).toBe("operational");
});
