import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../../src/domain/candidate.ts";
import { FakeClient } from "../../src/infer/client.ts";
import { detect } from "../../src/infer/detect.ts";
import {
  appendEvidence,
  type EvidenceRecord,
  readEvidence,
} from "../../src/record/evidence.ts";
import { readProposed } from "../../src/record/proposed.ts";
import { listPending } from "../../src/record/queue.ts";

let home: string;
let state: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  process.env.PRECEPT_HOME = home;
  process.env.PRECEPT_STATE_DIR = state;
});

afterEach(() => {
  delete process.env.PRECEPT_HOME;
  delete process.env.PRECEPT_STATE_DIR;
  rmSync(home, { recursive: true, force: true });
  rmSync(state, { recursive: true, force: true });
});

const ev = (id: string, turns: string): EvidenceRecord => ({
  id,
  at: "2026-09-08T10:00:00Z",
  signalKind: "stated-knowledge",
  turns,
  session: "s1",
  repository: "acme-api",
});

/** Counts the calls, so a test can assert what was actually paid for. */
function countingDetector(): { client: FakeClient; calls: () => number } {
  let calls = 0;
  const client = new FakeClient((e): Candidate | null => {
    calls++;
    if (!e.turns.startsWith("fyi ")) return null; // abstain
    return {
      kind: "knowledge",
      scope: { kind: "repository", repository: "acme-api" },
      content: e.turns.slice(4),
      condition: "always",
      signalKind: "stated-knowledge",
      evidenceId: e.id,
    };
  });
  return { client, calls: () => calls };
}

test("a second run over the same evidence sends nothing to the model", async () => {
  appendEvidence(ev("e1", "fyi staging runs on Render, prod is Fly.io"));
  const { client, calls } = countingDetector();

  const first = await detect(readEvidence(), client);
  expect(first.proposed).toBe(1);
  expect(first.queued).toBe(1);
  expect(first.alreadyProposed).toBe(0);
  expect(calls()).toBe(1);

  // The evidence log is append-only and read whole, so the second run sees the
  // same record again. It must not be paid for twice, and must not enqueue a
  // duplicate of the same window.
  const second = await detect(readEvidence(), client);
  expect(second.proposed).toBe(0);
  expect(second.queued).toBe(0);
  expect(second.alreadyProposed).toBe(1);
  expect(calls()).toBe(1);
  expect(listPending()).toHaveLength(1);
});

test("an abstention is still recorded, so it is not re-sent", async () => {
  // Abstention is the common outcome and leaves no trace in the queue or the
  // decision log, so the ledger has to record the send rather than the result.
  appendEvidence(ev("e1", "how do i run the tests"));
  const { client, calls } = countingDetector();

  const first = await detect(readEvidence(), client);
  expect(first.proposed).toBe(1);
  expect(first.queued).toBe(0);

  const second = await detect(readEvidence(), client);
  expect(second.alreadyProposed).toBe(1);
  expect(calls()).toBe(1);
});

test("only new evidence is sent on a later run", async () => {
  appendEvidence(ev("e1", "fyi staging runs on Render"));
  const { client, calls } = countingDetector();
  await detect(readEvidence(), client);

  appendEvidence(ev("e2", "fyi prod runs on Fly.io"));
  const second = await detect(readEvidence(), client);
  expect(second.alreadyProposed).toBe(1);
  expect(second.proposed).toBe(1);
  expect(second.queued).toBe(1);
  expect(calls()).toBe(2);
  expect(listPending()).toHaveLength(2);
});

test("filtered evidence is not marked proposed, so the gate can be revisited", async () => {
  // The pre-filter is free to re-run and the R1.14 hindsight pass wants a
  // second look at what the live gate skipped, so a filtered window stays out
  // of the ledger.
  appendEvidence({ ...ev("e1", "fix the failing test"), signalKind: "instruction" });
  const { client, calls } = countingDetector();

  const result = await detect(readEvidence(), client);
  expect(result.filtered).toBe(1);
  expect(result.proposed).toBe(0);
  expect(calls()).toBe(0);
  expect(readProposed().size).toBe(0);
});
