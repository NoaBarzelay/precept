import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../src/domain/candidate.ts";
import { runCli } from "../src/cli.ts";
import { review } from "../src/gate/gate.ts";
import { runInterception } from "../src/interception.ts";
import { readCard } from "../src/store/card.ts";

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

function authorProbationaryRule(): string {
  const c: Candidate = {
    kind: "rule",
    scope: { kind: "repository", repository: "acme-api" },
    content: "In a uv project, use uv, never plain pip.",
    condition: "the project uses uv",
    signalKind: "correction",
    tier: "hard",
    check: {
      op: "and",
      checks: [
        { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
        { op: "not", check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "uv pip" } },
      ],
    },
    example: { toolName: "Bash", toolInput: { command: "pip install httpx" }, permissionMode: "default" },
  };
  return review(c, { action: "keep" }, { now: "2026-07-19" }).entry!.id;
}

const pre = (command: string) =>
  JSON.stringify({ hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: { command } });

function decision(command: string): string {
  const out = JSON.parse(runInterception(pre(command))) as {
    hookSpecificOutput?: { permissionDecision?: string };
    continue?: boolean;
  };
  return out.hookSpecificOutput?.permissionDecision ?? (out.continue ? "allow" : "?");
}

test("a probationary rule asks, then graduates to deny after three confirmations", () => {
  const id = authorProbationaryRule();
  runCli(["compile"]);

  // Probationary: it asks, it does not deny (R1.19).
  expect(decision("pip install httpx")).toBe("ask");

  expect(runCli(["confirm", id])).toContain("1/3");
  runCli(["compile"]);
  expect(decision("pip install httpx")).toBe("ask");

  runCli(["confirm", id]);
  const third = runCli(["confirm", id]);
  expect(third).toContain("graduated");

  // Operational now: it denies (R1.21). uv pip still allowed.
  expect(decision("pip install httpx")).toBe("deny");
  expect(decision("uv pip install httpx")).toBe("allow");
  expect(readCard(id).lifecycle).toBe("operational");
});

test("a fourth confirmation is a safe no-op, not a double count", () => {
  const id = authorProbationaryRule();
  runCli(["confirm", id]);
  runCli(["confirm", id]);
  runCli(["confirm", id]); // graduates at 3
  const extra = runCli(["confirm", id]);
  expect(extra).toContain("already operational");
  expect(readCard(id).confirmations).toBe(3);
});

test("reject narrows the condition and resets the count", () => {
  const id = authorProbationaryRule();
  runCli(["confirm", id]);
  runCli(["confirm", id]);
  const out = runCli(["reject", id, "--condition", "uv project and not a scratch repo"]);
  expect(out).toContain("narrowed");
  const card = readCard(id);
  expect(card.confirmations).toBe(0);
  expect(card.validity.condition).toBe("uv project and not a scratch repo");
  expect(card.lifecycle).toBe("probationary");
});
