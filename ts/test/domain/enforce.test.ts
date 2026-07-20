import { expect, test } from "bun:test";
import { type CompiledRule, enforce } from "../../src/domain/enforce.ts";
import type { FactRecord } from "../../src/domain/facts.ts";

const bash = (command: string, over: Partial<FactRecord> = {}): FactRecord => ({
  toolName: "Bash",
  toolInput: { command },
  permissionMode: "default",
  ...over,
});

const denyPip: CompiledRule = {
  id: "uv-not-pip",
  outcome: "deny",
  reason: "use uv, never plain pip",
  check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
};

const askEnvelope: CompiledRule = {
  id: "envelope",
  outcome: "ask",
  reason: "responses go through envelope()",
  check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "return {" },
};

test("no rule matches: allow", () => {
  expect(enforce(bash("ls -la"), [denyPip, askEnvelope]).outcome).toBe("allow");
});

test("an operational rule denies", () => {
  const d = enforce(bash("pip install httpx"), [denyPip]);
  expect(d.outcome).toBe("deny");
  expect(d.ruleId).toBe("uv-not-pip");
  expect(d.reason).toContain("uv");
});

test("deny outranks ask regardless of order", () => {
  const facts = bash("pip install x; return { ok: true }");
  expect(enforce(facts, [askEnvelope, denyPip]).outcome).toBe("deny");
  expect(enforce(facts, [denyPip, askEnvelope]).outcome).toBe("deny");
});

test("a probationary rule only asks", () => {
  expect(enforce(bash("return { ok: true }"), [askEnvelope]).outcome).toBe("ask");
});

test("a malformed rule fails toward allow, never throws", () => {
  const broken = {
    id: "broken",
    outcome: "deny",
    reason: "x",
    check: { op: "bogus", field: { kind: "tool" } },
  } as unknown as CompiledRule;
  expect(enforce(bash("pip install x"), [broken, denyPip]).outcome).toBe("deny");
  expect(enforce(bash("ls"), [broken]).outcome).toBe("allow");
});
