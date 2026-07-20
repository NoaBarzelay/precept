import { afterEach, expect, test } from "bun:test";
import { runInjection } from "../src/injection.ts";
import { runInterception } from "../src/interception.ts";
import { runObservation } from "../src/observation.ts";

afterEach(() => {
  delete process.env.PRECEPT_INFERENCE_SUBPROCESS;
});

// The fork-bomb fix (Python history): a claude call Precept spawned sets the
// sentinel, and every hook entrypoint no-ops under it so it cannot re-fire
// Precept's hooks.
const pre = JSON.stringify({ hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: { command: "pip install x" } });
const prompt = JSON.stringify({ hook_event_name: "UserPromptSubmit", prompt: "hi" });
const post = JSON.stringify({ hook_event_name: "PostToolUse", tool_name: "Bash", tool_input: { command: "ls" } });

test("every hook entrypoint no-ops under the subprocess sentinel", () => {
  process.env.PRECEPT_INFERENCE_SUBPROCESS = "1";
  expect(JSON.parse(runInterception(pre)).continue).toBe(true);
  expect(JSON.parse(runInjection(prompt)).continue).toBe(true);
  expect(JSON.parse(runObservation(post)).continue).toBe(true);
});
