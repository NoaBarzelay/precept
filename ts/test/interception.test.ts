import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "./../src/domain/candidate.ts";
import { review } from "../src/gate/gate.ts";
import { runInterception } from "../src/interception.ts";
import { compile, readProjection, writeProjection } from "../src/projection/projection.ts";
import { allEntries, writeCard } from "../src/store/card.ts";
import { faultsLogPath } from "../src/store/paths.ts";
import { readLines } from "../src/record/log.ts";

let home: string;
let state: string;
let repo: string; // a working dir inside a repo named acme-api

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  process.env.PRECEPT_HOME = home;
  process.env.PRECEPT_STATE_DIR = state;
  repo = join(home, "acme-api");
  mkdirSync(join(repo, ".git"), { recursive: true });
  writeFileSync(join(repo, ".git", "HEAD"), "ref: refs/heads/main\n");
});

afterEach(() => {
  delete process.env.PRECEPT_HOME;
  delete process.env.PRECEPT_STATE_DIR;
  rmSync(home, { recursive: true, force: true });
  rmSync(state, { recursive: true, force: true });
});

// A user correction that becomes a hard rule, then graduates to operational so
// it can deny (in real use, three confirmations; here we set it directly).
function commitOperationalRule(): void {
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
  const { entry } = review(c, { action: "keep" }, { now: "2026-07-19" });
  // graduate it: rewrite the card as operational (probation lifecycle is a
  // later runtime batch; here we compile it operational to test the hot path)
  writeCard({ ...entry!, lifecycle: "operational" as const });
}

const preToolUse = (command: string, cwd = repo) =>
  JSON.stringify({
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: { command },
    cwd,
  });

test("compile turns a live hard rule into a projection entry", () => {
  commitOperationalRule();
  const rules = compile(allEntries());
  expect(rules.length).toBe(1);
  expect(rules[0]!.outcome).toBe("deny");
});

test("a probationary hard rule compiles to ask, not deny", () => {
  const c: Candidate = {
    kind: "rule",
    scope: { kind: "global" },
    content: "no direct commits to main",
    condition: "shared repo",
    signalKind: "correction",
    tier: "hard",
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "git commit" },
    example: { toolName: "Bash", toolInput: { command: "git commit -m x" }, permissionMode: "default" },
  };
  review(c, { action: "keep" }, { now: "2026-07-19" }); // stays probationary
  expect(compile(allEntries())[0]!.outcome).toBe("ask");
});

test("interception denies a matching call and allows others", () => {
  commitOperationalRule();
  writeProjection(compile(allEntries()));

  const denied = JSON.parse(runInterception(preToolUse("pip install httpx"))) as {
    hookSpecificOutput?: { permissionDecision?: string; permissionDecisionReason?: string };
  };
  expect(denied.hookSpecificOutput?.permissionDecision).toBe("deny");
  expect(denied.hookSpecificOutput?.permissionDecisionReason).toContain("uv");

  const allowed = JSON.parse(runInterception(preToolUse("uv pip install httpx"))) as Record<string, unknown>;
  expect(allowed.continue).toBe(true);
});

test("a repo-scoped rule does not fire outside its repo (README Risk 2)", () => {
  commitOperationalRule(); // scoped to repository acme-api
  writeProjection(compile(allEntries()));

  // In acme-api: denied.
  expect(
    (JSON.parse(runInterception(preToolUse("pip install httpx", repo))) as {
      hookSpecificOutput?: { permissionDecision?: string };
    }).hookSpecificOutput?.permissionDecision,
  ).toBe("deny");

  // In a scratch dir that is not the acme-api repo: allowed.
  const scratch = join(home, "scratch");
  const out = JSON.parse(runInterception(preToolUse("pip install httpx", scratch))) as Record<string, unknown>;
  expect(out.continue).toBe(true);
});

test("non-PreToolUse events pass through", () => {
  const out = JSON.parse(runInterception(JSON.stringify({ hook_event_name: "SessionStart" }))) as Record<string, unknown>;
  expect(out.continue).toBe(true);
});

test("fails open and records the fault on malformed input (N1)", () => {
  // A corrupt projection makes readProjection throw at parse.
  writeFileSync(join(state, "policies.json"), "{ not valid json");
  const out = JSON.parse(runInterception(preToolUse("pip install x"))) as Record<string, unknown>;
  expect(out.continue).toBe(true);
  const faults = readLines<{ stage: string }>(faultsLogPath());
  expect(faults.some((f) => f.stage === "interception")).toBe(true);
});

test("a rule that throws at enforcement fails open and records a fault (N1)", () => {
  // Hand-corrupt the projection with a malformed regex the compiler would reject.
  writeProjection([
    { id: "bad-regex", outcome: "deny", reason: "x", check: { op: "str.regex", field: { kind: "input", key: "command" }, pattern: "a(b" } },
  ] as never);
  const out = JSON.parse(runInterception(preToolUse("pip install x"))) as Record<string, unknown>;
  expect(out.continue).toBe(true); // failed open
  const faults = readLines<{ stage: string; ruleId?: string }>(faultsLogPath());
  expect(faults.some((f) => f.stage === "enforce" && f.ruleId === "bad-regex")).toBe(true);
});

test("an empty catalog compiles to an empty projection, everything allowed", () => {
  writeProjection(compile(allEntries()));
  expect(readProjection()).toEqual([]);
  const out = JSON.parse(runInterception(preToolUse("pip install x"))) as Record<string, unknown>;
  expect(out.continue).toBe(true);
});
