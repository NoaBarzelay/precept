import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Candidate } from "../../src/domain/candidate.ts";
import { runInjection } from "../../src/injection.ts";
import { backlogPrompt, stampPrompted } from "../../src/record/backlog.ts";
import { enqueue } from "../../src/record/queue.ts";
import { backlogStampPath } from "../../src/store/paths.ts";

let home: string;
let state: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  process.env.PRECEPT_HOME = home;
  process.env.PRECEPT_STATE_DIR = state;
  process.env.PRECEPT_BACKLOG_INTERVAL_HOURS = "0"; // no throttle unless a test sets one
});

afterEach(() => {
  delete process.env.PRECEPT_HOME;
  delete process.env.PRECEPT_STATE_DIR;
  delete process.env.PRECEPT_BACKLOG_INTERVAL_HOURS;
  rmSync(home, { recursive: true, force: true });
  rmSync(state, { recursive: true, force: true });
});

const candidate = (content: string, kind: Candidate["kind"] = "knowledge"): Candidate => ({
  kind,
  scope: { kind: "global" },
  content,
  condition: "always",
  signalKind: "stated-knowledge",
});

const sessionStart = JSON.stringify({
  hook_event_name: "SessionStart",
  cwd: "/work/acme",
});

test("an empty queue says nothing", () => {
  expect(backlogPrompt()).toBe("");
  expect(runInjection(sessionStart)).toBe(JSON.stringify({ continue: true }));
});

test("a queue reports its size, kinds, and a few previews", () => {
  enqueue(candidate("staging runs on Render, prod is Fly.io"));
  enqueue(candidate("always cross-check PitchBook against press", "convention"));
  enqueue(candidate("decode is memory-bound"));

  const text = backlogPrompt();
  expect(text).toContain("3 candidates awaiting review");
  expect(text).toContain("2 knowledge, 1 convention");
  expect(text).toContain("Render");
  expect(text).toContain("interactively");
});

test("the prompt stays bounded as the queue grows", () => {
  for (let i = 0; i < 3; i++) enqueue(candidate(`short item ${i}`));
  const small = backlogPrompt().length;

  for (let i = 0; i < 200; i++) enqueue(candidate(`filler item ${i} `.repeat(40)));
  const large = backlogPrompt();

  // A queue of 203 must not cost meaningfully more context than a queue of 3:
  // fixed summary plus at most three truncated previews.
  expect(large).toContain("203 candidates");
  expect(large.length).toBeLessThan(small + 200);
  expect(large.length).toBeLessThan(1200);
});

test("the throttle suppresses a repeat prompt, then lets it through", () => {
  process.env.PRECEPT_BACKLOG_INTERVAL_HOURS = "24";
  enqueue(candidate("something to review"));

  const now = new Date("2026-09-08T10:00:00Z");
  expect(backlogPrompt(now)).not.toBe("");
  stampPrompted(now);

  const anHourLater = new Date("2026-09-08T11:00:00Z");
  expect(backlogPrompt(anHourLater)).toBe("");

  const twoDaysLater = new Date("2026-09-10T10:00:00Z");
  expect(backlogPrompt(twoDaysLater)).not.toBe("");
});

test("SessionStart injects the prompt and stamps only when it does", () => {
  process.env.PRECEPT_BACKLOG_INTERVAL_HOURS = "24";
  // Nothing queued: no injection, and no stamp, so the first real backlog is
  // not silently swallowed by a quiet interval that never showed anything.
  expect(runInjection(sessionStart)).toBe(JSON.stringify({ continue: true }));
  expect(existsSync(backlogStampPath())).toBe(false);

  enqueue(candidate("staging runs on Render"));
  const out = JSON.parse(runInjection(sessionStart)) as {
    hookSpecificOutput: { hookEventName: string; additionalContext: string };
  };
  expect(out.hookSpecificOutput.hookEventName).toBe("SessionStart");
  expect(out.hookSpecificOutput.additionalContext).toContain("1 candidate awaiting review");
  expect(existsSync(backlogStampPath())).toBe(true);

  // Immediately after, the throttle holds.
  expect(runInjection(sessionStart)).toBe(JSON.stringify({ continue: true }));
});

test("the hook stays silent under the subprocess sentinel", () => {
  enqueue(candidate("something to review"));
  process.env.PRECEPT_INFERENCE_SUBPROCESS = "1";
  try {
    expect(runInjection(sessionStart)).toBe(JSON.stringify({ continue: true }));
  } finally {
    delete process.env.PRECEPT_INFERENCE_SUBPROCESS;
  }
});
