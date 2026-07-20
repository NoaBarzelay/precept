import { expect, test } from "bun:test";
import type { Check } from "../../src/domain/check.ts";
import type { FactRecord } from "../../src/domain/facts.ts";
import { firing, reachable, subsumes } from "../../src/domain/validate.ts";

const bash = (command: string): FactRecord => ({
  toolName: "Bash",
  toolInput: { command },
  permissionMode: "default",
});

const pipInstall: Check = {
  op: "str.contains",
  field: { kind: "input", key: "command" },
  value: "pip install",
};

const history = [
  bash("pip install httpx"),
  bash("cd api && pip install stripe"),
  bash("uv pip install ruff"),
  bash("ls -la"),
  bash("git status"),
];

test("reachable is true when a recorded call matches", () => {
  expect(reachable(pipInstall, history)).toBe(true);
});

test("reachable falls back to a reviewed example when history has no match", () => {
  const never: Check = { op: "str.contains", field: { kind: "input", key: "command" }, value: "terraform apply" };
  expect(reachable(never, history)).toBe(false);
  expect(reachable(never, history, [bash("terraform apply -auto-approve")])).toBe(true);
});

test("a malformed check is never reachable, never throws", () => {
  const bad = { op: "bogus" } as unknown as Check;
  expect(reachable(bad, history, [bash("anything")])).toBe(false);
});

test("firing counts matches and returns examples", () => {
  const f = firing(pipInstall, history);
  expect(f.count).toBe(3); // three commands contain "pip install"
  expect(f.examples.length).toBeLessThanOrEqual(3);
  expect(f.examples[0]!.toolInput.command).toContain("pip install");
});

test("subsumes: a narrower check adds no coverage over a broader one", () => {
  const broader = pipInstall;
  const narrower: Check = { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install httpx" };
  expect(subsumes(broader, narrower, history)).toBe(true);
  // reversed: broader is not subsumed by narrower (broader fires where narrower does not)
  expect(subsumes(narrower, broader, history)).toBe(false);
});
