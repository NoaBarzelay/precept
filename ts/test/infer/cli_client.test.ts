import { expect, test } from "bun:test";
import {
  CliClient,
  parseStructured,
  type Runner,
  toCandidate,
} from "../../src/infer/cli_client.ts";
import type { EvidenceRecord } from "../../src/record/evidence.ts";

const ev: EvidenceRecord = {
  id: "e1",
  at: "2026-07-20T10:00:00Z",
  signalKind: "stated-knowledge",
  turns: "fyi staging runs on Render, prod is Fly.io",
  session: "s1",
  repository: "acme-api",
};

// A fake runner returning a canned claude -p envelope, so prompt/schema/parse
// are tested with no live model.
const runnerReturning = (structured: unknown): Runner => async () =>
  JSON.stringify({ type: "result", structured_output: structured });

test("parses a structured envelope into a candidate", async () => {
  const client = new CliClient(
    runnerReturning({
      abstain: false,
      kind: "knowledge",
      content: "Staging runs on Render, prod is Fly.io",
      condition: "always",
      scopeKind: "repository",
      scopeValue: "acme-api",
    }),
  );
  const c = await client.propose(ev);
  expect(c).not.toBeNull();
  expect(c!.kind).toBe("knowledge");
  expect(c!.scope).toEqual({ kind: "repository", repository: "acme-api" });
  expect(c!.signalKind).toBe("stated-knowledge"); // taken from the evidence
  expect(c!.evidenceId).toBe("e1");
});

test("abstains when the model abstains", async () => {
  const client = new CliClient(runnerReturning({ abstain: true }));
  expect(await client.propose(ev)).toBeNull();
});

test("drops a malformed extraction rather than guessing", async () => {
  const client = new CliClient(runnerReturning({ abstain: false, kind: "knowledge" })); // no content
  expect(await client.propose(ev)).toBeNull();
});

test("abstains when the model is unreachable (runner throws)", async () => {
  const client = new CliClient(async () => {
    throw new Error("claude: not found");
  });
  expect(await client.propose(ev)).toBeNull();
});

test("parseStructured tolerates envelope shapes and bad JSON", () => {
  expect(parseStructured('{"structured_output":{"abstain":true}}')).toEqual({ abstain: true });
  expect(parseStructured('{"result":{"abstain":false,"kind":"knowledge"}}')).toEqual({ abstain: false, kind: "knowledge" });
  expect(parseStructured("not json")).toBeNull();
});

test("toCandidate defaults an unknown scope to global", () => {
  const c = toCandidate(
    { abstain: false, kind: "convention", content: "use envelope()", condition: "in this repo" },
    ev,
  );
  expect(c!.scope).toEqual({ kind: "global" });
  expect(c!.kind).toBe("convention");
});
