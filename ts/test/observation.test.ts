import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../src/domain/candidate.ts";
import { review } from "../src/gate/gate.ts";
import { runObservation } from "../src/observation.ts";
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
