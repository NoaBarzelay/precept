import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../../src/domain/candidate.ts";
import { readCard } from "../../src/store/card.ts";
import { cardPath } from "../../src/store/paths.ts";
import { FakeClient } from "../../src/infer/client.ts";
import { capture } from "../../src/infer/capture.ts";
import { review } from "../../src/gate/gate.ts";
import { readDecisions } from "../../src/record/decision.ts";
import { readEvidence, type EvidenceRecord } from "../../src/record/evidence.ts";
import { Index } from "../../src/retrieve/index.ts";

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

const ev = (over: Partial<EvidenceRecord> = {}): EvidenceRecord => ({
  id: "ev-1",
  at: "2026-07-19T10:00:00Z",
  signalKind: "stated-knowledge",
  turns: "fyi staging runs on Render, prod is Fly.io",
  session: "s1",
  repository: "acme-api",
  ...over,
});

const knowledgeCandidate = (over: Partial<Candidate> = {}): Candidate => ({
  kind: "knowledge",
  scope: { kind: "repository", repository: "acme-api" },
  content: "Staging runs on Render, prod is Fly.io.",
  condition: "always",
  signalKind: "stated-knowledge",
  evidenceId: "ev-1",
  quote: "fyi staging runs on Render",
  ...over,
});

test("capture records evidence and returns a candidate", async () => {
  const client = new FakeClient(() => knowledgeCandidate());
  const candidate = await capture(ev(), client);
  expect(candidate).not.toBeNull();
  expect(readEvidence()).toHaveLength(1);
});

test("capture abstains: evidence kept, no candidate (R1.2, R2.2)", async () => {
  const client = new FakeClient(() => null);
  const candidate = await capture(ev({ turns: "hmm, not sure" }), client);
  expect(candidate).toBeNull();
  expect(readEvidence()).toHaveLength(1); // evidence stays for the hindsight audit
});

test("keep commits a card, indexes it, and records a decision (N7)", async () => {
  const candidate = knowledgeCandidate();
  const { decision, entry } = review(candidate, { action: "keep" }, { now: "2026-07-19" });

  expect(entry).toBeDefined();
  expect(existsSync(cardPath(entry!.id))).toBe(true);
  expect(readCard(entry!.id).content).toContain("Render");

  const idx = new Index();
  idx.rebuild();
  expect(idx.search("staging render").length).toBeGreaterThan(0);
  idx.close();

  const decisions = readDecisions();
  expect(decisions).toHaveLength(1);
  expect(decisions[0]!.action).toBe("keep");
  expect(decisions[0]!.entryId).toBe(entry!.id);
  // The entry points back to the decision that authorized it (N6).
  expect(entry!.provenance.decisionId).toBe(decision.id);
});

test("dismiss records a decision and writes no card", () => {
  const before = existsSync(home);
  const { decision, entry } = review(
    knowledgeCandidate(),
    { action: "dismiss", reason: "not a durable fact" },
  );
  expect(entry).toBeUndefined();
  expect(decision.action).toBe("dismiss");
  expect(readDecisions()).toHaveLength(1);
  // no entries dir created for a dismiss
  expect(existsSync(join(home, "entries"))).toBe(before ? false : false);
});

test("correct commits the corrected candidate and records the delta (R1.13)", () => {
  const proposed = knowledgeCandidate({ content: "Staging runs on Heroku." });
  const corrected = knowledgeCandidate({ content: "Staging runs on Render, prod is Fly.io." });
  const { decision, entry } = review(
    proposed,
    { action: "correct", corrected },
    { now: "2026-07-19" },
  );
  expect(entry!.content).toContain("Render");
  expect(decision.delta).toBeDefined();
  expect(decision.delta!.changed).toContain("content");
});

test("provenance gate: a silent edit cannot source a blocking entry", () => {
  const proposed: Candidate = {
    kind: "rule",
    scope: { kind: "repository", repository: "acme-api" },
    content: "API responses go through envelope().",
    condition: "in this repo",
    signalKind: "silent-edit",
    tier: "hard",
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "return {" },
  };
  const { entry } = review(proposed, { action: "keep" }, { now: "2026-07-19" });
  // Downgraded to soft: it steers, it does not block.
  expect(entry!.tier).toBe("soft");
  expect(entry!.check).toBeUndefined();
});

test("a user correction may source a hard rule, entering probation", () => {
  const proposed: Candidate = {
    kind: "rule",
    scope: { kind: "repository", repository: "acme-api" },
    content: "In a uv project, use uv, never plain pip.",
    condition: "the project uses uv",
    signalKind: "correction",
    tier: "hard",
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
    example: { toolName: "Bash", toolInput: { command: "pip install httpx" }, permissionMode: "default" },
  };
  const { entry } = review(proposed, { action: "keep" }, { now: "2026-07-19" });
  expect(entry!.tier).toBe("hard");
  expect(entry!.lifecycle).toBe("probationary");
  expect(entry!.confirmations).toBe(0);
});
