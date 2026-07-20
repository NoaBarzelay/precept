import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../src/domain/candidate.ts";
import { keepCmd, dismissCmd, pendingCmd } from "../src/cli.ts";
import { FakeClient } from "../src/infer/client.ts";
import { detect } from "../src/infer/detect.ts";
import { appendEvidence, type EvidenceRecord } from "../src/record/evidence.ts";
import { listPending } from "../src/record/queue.ts";
import { readDecisions } from "../src/record/decision.ts";
import { allEntries } from "../src/store/card.ts";
import { Index } from "../src/retrieve/index.ts";

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
  at: "2026-07-20T10:00:00Z",
  signalKind: "stated-knowledge",
  turns,
  session: "s1",
  repository: "acme-api",
});

// A fake detector: propose a knowledge candidate from an "fyi ..." turn, abstain
// otherwise. This stands in for the real model behind the same interface.
const fakeDetector = new FakeClient((e): Candidate | null => {
  if (!e.turns.startsWith("fyi ")) return null; // abstain (R1.2, R2.2)
  return {
    kind: "knowledge",
    scope: { kind: "repository", repository: "acme-api" },
    content: e.turns.slice(4),
    condition: "always",
    signalKind: "stated-knowledge",
    evidenceId: e.id,
  };
});

test("the loop runs live: evidence -> detect -> queue -> keep -> catalog", async () => {
  appendEvidence(ev("e1", "fyi staging runs on Render, prod is Fly.io"));
  appendEvidence(ev("e2", "how do i run the tests")); // not a durable fact

  // Import readEvidence lazily to run detection over what was recorded.
  const { readEvidence } = await import("../src/record/evidence.ts");
  const { queued } = await detect(readEvidence(), fakeDetector);
  expect(queued).toBe(1); // the "how do i" turn abstains

  const pending = listPending();
  expect(pending).toHaveLength(1);
  expect(pendingCmd()).toContain("Render");

  // Keep it: it commits through the gate (a decision is recorded, N7) and
  // leaves the queue.
  const out = keepCmd(pending[0]!.id);
  expect(out).toMatch(/^kept /);
  expect(listPending()).toHaveLength(0);
  expect(allEntries()).toHaveLength(1);
  expect(readDecisions()).toHaveLength(1);

  // And it is retrievable in a later session.
  const idx = new Index();
  idx.rebuild();
  expect(idx.search("where does staging run").length).toBeGreaterThan(0);
  idx.close();
});

test("dismiss records a decision and commits nothing", async () => {
  appendEvidence(ev("e1", "fyi we deploy on Fridays"));
  const { readEvidence } = await import("../src/record/evidence.ts");
  await detect(readEvidence(), fakeDetector);
  const id = listPending()[0]!.id;

  expect(dismissCmd([id, "not", "durable"])).toBe(`dismissed ${id}`);
  expect(listPending()).toHaveLength(0);
  expect(allEntries()).toHaveLength(0);
  expect(readDecisions()[0]!.action).toBe("dismiss");
});

test("detection abstains on every record when the backend abstains", async () => {
  appendEvidence(ev("e1", "just some chatter"));
  const abstain = new FakeClient(() => null);
  const { readEvidence } = await import("../src/record/evidence.ts");
  expect((await detect(readEvidence(), abstain)).queued).toBe(0);
  expect(listPending()).toHaveLength(0);
});

test("the cost gate skips the model for a plain instruction turn", async () => {
  appendEvidence({
    id: "i1",
    at: "2026-07-20T10:00:00Z",
    signalKind: "instruction",
    turns: "user: add a health endpoint", // a one-off task, no durable cue
    session: "s1",
  });
  appendEvidence({
    id: "i2",
    at: "2026-07-20T10:01:00Z",
    signalKind: "instruction",
    turns: "user: always run the tests before committing", // durable
    session: "s1",
  });
  let calls = 0;
  const counting = new FakeClient((e) => {
    calls++;
    return {
      kind: "convention",
      scope: { kind: "global" },
      content: e.turns,
      condition: "always",
      signalKind: "instruction",
      evidenceId: e.id,
    };
  });
  const { readEvidence } = await import("../src/record/evidence.ts");
  const result = await detect(readEvidence(), counting);
  expect(calls).toBe(1); // only the durable instruction reached the model
  expect(result.proposed).toBe(1);
  expect(result.filtered).toBe(1);
  expect(result.queued).toBe(1);
});

test("keep/dismiss on an unknown pending id are reported, not thrown", () => {
  expect(keepCmd("nope")).toBe("no pending candidate nope");
  expect(dismissCmd(["nope"])).toBe("no pending candidate nope");
  expect(existsSync(join(state, "pending"))).toBe(false);
});
