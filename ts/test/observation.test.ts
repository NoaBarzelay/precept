import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../src/domain/candidate.ts";
import { review } from "../src/gate/gate.ts";
import { observeSession, runObservation } from "../src/observation.ts";
import { readCursor } from "../src/record/cursor.ts";
import { readEvidence } from "../src/record/evidence.ts";
import { readHistory } from "../src/record/history.ts";

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

const post = (command: string) =>
  JSON.stringify({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command } });

test("observation records a PostToolUse call to history", () => {
  runObservation(post("pip install httpx"));
  runObservation(post("ls -la"));
  const h = readHistory();
  expect(h).toHaveLength(2);
  expect(h[0]!.facts.toolInput.command).toBe("pip install httpx");
});

test("observation ignores non-PostToolUse events", () => {
  runObservation(JSON.stringify({ hook_event_name: "SessionStart" }));
  expect(readHistory()).toHaveLength(0);
});

const transcript = (...lines: object[]) =>
  lines.map((l) => JSON.stringify(l)).join("\n");

test("SessionEnd drafts evidence from the transcript and advances the cursor", () => {
  const path = join(state, "session.jsonl");
  writeFileSync(
    path,
    transcript(
      { type: "user", message: { role: "user", content: "always run tests first" } },
      { type: "assistant", message: { role: "assistant", content: [{ type: "text", text: "ok" }] } },
    ),
  );
  const out = runObservation(
    JSON.stringify({ hook_event_name: "SessionEnd", session_id: "s1", transcript_path: path }),
  );
  expect(JSON.parse(out).continue).toBe(true); // fail-open shape, never blocks
  const ev = readEvidence();
  expect(ev).toHaveLength(1);
  expect(ev[0]!.turns).toContain("always run tests first");
  expect(readCursor("s1")).toBe(2);
});

test("a re-fired SessionEnd is idempotent (cursor + id dedup)", () => {
  const path = join(state, "session.jsonl");
  writeFileSync(
    path,
    transcript({ type: "user", message: { role: "user", content: "one instruction" } }),
  );
  const event = { kind: "SessionEnd" as const, sessionId: "s1", transcriptPath: path };
  expect(observeSession(event)).toBe(1);
  expect(observeSession(event)).toBe(0); // nothing new the second time
  expect(readEvidence()).toHaveLength(1);
});

test("SessionEnd with no transcript path records nothing and does not throw", () => {
  const out = runObservation(JSON.stringify({ hook_event_name: "SessionEnd", session_id: "s1" }));
  expect(JSON.parse(out).continue).toBe(true);
  expect(readEvidence()).toHaveLength(0);
});

test("a hard rule reachable only through prior history keeps its teeth", () => {
  // The correction arrives with no example, but the offending call is in history.
  runObservation(post("pip install httpx"));
  const c: Candidate = {
    kind: "rule",
    scope: { kind: "global" },
    content: "use uv, never plain pip",
    condition: "uv project",
    signalKind: "correction",
    tier: "hard",
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
  };
  const { entry } = review(c, { action: "keep" }, { now: "2026-07-19" });
  expect(entry!.tier).toBe("hard"); // history supplied the reachability witness
});

test("a hard rule with neither history nor example degrades to guidance", () => {
  const c: Candidate = {
    kind: "rule",
    scope: { kind: "global" },
    content: "never run terraform apply directly",
    condition: "always",
    signalKind: "correction",
    tier: "hard",
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "terraform apply" },
  };
  const { entry } = review(c, { action: "keep" }, { now: "2026-07-19" });
  expect(entry!.tier).toBe("soft"); // no demonstrated match, so it steers
  expect(entry!.check).toBeUndefined();
});
