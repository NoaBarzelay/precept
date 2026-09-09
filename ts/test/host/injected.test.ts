import { expect, test } from "bun:test";
import { parseTranscript, stripInjected } from "../../src/host/transcript.ts";

const userLine = (text: string) =>
  JSON.stringify({ type: "user", message: { role: "user", content: text } });

test("a turn that is only a task notification is not a human turn", () => {
  // This is the failure that put 22 notes in the vault claiming Noa had made a
  // correction, when a background research agent had simply finished.
  const notification =
    "<task-notification>\n<task-id>ab3c55f</task-id>\n<status>completed</status>\n</task-notification>";
  expect(stripInjected(notification)).toBe("");
  const [entry] = parseTranscript(userLine(notification));
  expect(entry!.humanTyped).toBe(false);
});

test("every injected wrapper the host uses is recognised", () => {
  for (const tag of [
    "task-notification",
    "system-reminder",
    "ci-monitor-event",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "user-prompt-submit-hook",
  ]) {
    expect(stripInjected(`<${tag}>content</${tag}>`)).toBe("");
  }
});

test("her own words survive when wrapped around an injected block", () => {
  // Discarding the whole turn would lose a real correction, so strip rather
  // than drop.
  const mixed =
    "<system-reminder>Be concise.</system-reminder>\nno, use the hazard model instead";
  expect(stripInjected(mixed)).toBe("no, use the hazard model instead");
  const [entry] = parseTranscript(userLine(mixed));
  expect(entry!.humanTyped).toBe(true);
  expect(entry!.text).toBe("no, use the hazard model instead");
});

test("multiple blocks in one turn are all removed", () => {
  const t = "<system-reminder>a</system-reminder>real text<task-notification>b</task-notification>";
  expect(stripInjected(t)).toBe("real text");
});

test("a plain turn is untouched", () => {
  const t = "why is decode memory bound? explain from first principles";
  expect(stripInjected(t)).toBe(t);
  expect(parseTranscript(userLine(t))[0]!.humanTyped).toBe(true);
});

test("prose containing an angle bracket is not mistaken for a wrapper", () => {
  const t = "use a < b as the guard, not a <= b";
  expect(stripInjected(t)).toBe(t);
});
