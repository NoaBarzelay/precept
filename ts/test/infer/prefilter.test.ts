import { expect, test } from "bun:test";
import type { EvidenceRecord } from "../../src/record/evidence.ts";
import type { SignalKind } from "../../src/domain/entry.ts";
import { worthProposing } from "../../src/infer/prefilter.ts";

const ev = (signalKind: SignalKind, turns: string): EvidenceRecord => ({
  id: "e",
  at: "2026-07-20T10:00:00Z",
  signalKind,
  turns,
  session: "s1",
});

test("every non-instruction signal always warrants a call", () => {
  for (const k of ["correction", "silent-edit", "stated-knowledge", "agent-research"] as const) {
    expect(worthProposing(ev(k, "user: whatever"))).toBe(true);
  }
});

test("a plain task-request instruction is filtered", () => {
  expect(worthProposing(ev("instruction", "user: add a health endpoint"))).toBe(false);
  expect(worthProposing(ev("instruction", "user: fix the failing build"))).toBe(false);
});

test("an instruction stating a durable preference passes the gate", () => {
  expect(worthProposing(ev("instruction", "user: always run the tests before committing"))).toBe(true);
  expect(worthProposing(ev("instruction", "user: use pnpm for this project"))).toBe(true);
  expect(worthProposing(ev("instruction", "user: we deploy on Fridays only"))).toBe(true);
});

test("the gate reads the human turn, not the surrounding context", () => {
  // The assistant's earlier turn mentions "always"; the human turn is a plain
  // task request, so it is still filtered.
  const turns = "assistant: I always add validation\n---\nuser: add the login page";
  expect(worthProposing(ev("instruction", turns))).toBe(false);
});
