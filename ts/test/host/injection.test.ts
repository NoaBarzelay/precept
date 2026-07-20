import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../../src/domain/candidate.ts";
import { review } from "../../src/gate/gate.ts";
import { parseEvent } from "../../src/host/claude_code.ts";
import { runInjection } from "../../src/injection.ts";

const FIXTURES = new URL("../fixtures/", import.meta.url).pathname;

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

function seedKnowledge(): void {
  const c: Candidate = {
    kind: "knowledge",
    scope: { kind: "repository", repository: "acme-api" },
    content: "Staging runs on Render (prod is Fly.io, acme-api).",
    condition: "always",
    signalKind: "stated-knowledge",
  };
  review(c, { action: "keep" }, { now: "2026-07-19" });
}

// Recorded host-event fixtures replayed against the adapter: the drift
// fitness function (ARCHITECTURE section 9). If the contract shape changes,
// these parse tests fail before a silent no-op ships.
test("parses the recorded UserPromptSubmit fixture", () => {
  const raw = readFileSync(join(FIXTURES, "user_prompt_submit.json"), "utf8");
  const ev = parseEvent(raw);
  expect(ev.kind).toBe("UserPromptSubmit");
  if (ev.kind === "UserPromptSubmit") {
    expect(ev.prompt).toContain("staging deploy");
    expect(ev.cwd).toContain("acme-api");
  }
});

test("parses the recorded SessionStart fixture", () => {
  const raw = readFileSync(join(FIXTURES, "session_start.json"), "utf8");
  expect(parseEvent(raw).kind).toBe("SessionStart");
});

test("tolerates an unknown event as Other, not an error", () => {
  expect(parseEvent(JSON.stringify({ hook_event_name: "PreCompact" })).kind).toBe("Other");
});

test("injects relevant knowledge on a matching prompt", () => {
  seedKnowledge();
  const raw = readFileSync(join(FIXTURES, "user_prompt_submit.json"), "utf8");
  const out = JSON.parse(runInjection(raw)) as {
    hookSpecificOutput?: { additionalContext?: string };
  };
  expect(out.hookSpecificOutput?.additionalContext).toContain("Render");
});

test("injects nothing when no knowledge is relevant", () => {
  seedKnowledge();
  const raw = JSON.stringify({
    hook_event_name: "UserPromptSubmit",
    prompt: "what is the capital of France",
  });
  const out = JSON.parse(runInjection(raw)) as Record<string, unknown>;
  expect(out.hookSpecificOutput).toBeUndefined();
  expect(out.continue).toBe(true);
});

test("fails open on malformed input (N1)", () => {
  const out = JSON.parse(runInjection("not json at all")) as Record<string, unknown>;
  expect(out.continue).toBe(true);
});

test("non-injecting events pass through", () => {
  const raw = readFileSync(join(FIXTURES, "session_start.json"), "utf8");
  const out = JSON.parse(runInjection(raw)) as Record<string, unknown>;
  expect(out.continue).toBe(true);
});
