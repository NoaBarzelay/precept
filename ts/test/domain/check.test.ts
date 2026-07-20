import { expect, test } from "bun:test";
import { type Check, checkError, evaluate } from "../../src/domain/check.ts";
import type { FactRecord } from "../../src/domain/facts.ts";

function bash(command: string, extra: Partial<FactRecord> = {}): FactRecord {
  return {
    toolName: "Bash",
    toolInput: { command },
    permissionMode: "default",
    ...extra,
  };
}

// The README's first usage example: in a uv project, never plain pip. The
// canonical invocations do not match on a prefix or suffix, which is why
// substring containment is in the grammar (ARCHITECTURE 5.1).
const noPlainPip: Check = {
  op: "and",
  checks: [
    { op: "str.eq", field: { kind: "tool" }, value: "Bash" },
    { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
    { op: "not", check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "uv pip" } },
  ],
};

test("blocks plain pip in its real invocations", () => {
  expect(evaluate(noPlainPip, bash("pip install httpx"))).toBe(true);
  expect(evaluate(noPlainPip, bash("cd api && pip install httpx"))).toBe(true);
  expect(evaluate(noPlainPip, bash("python -m pip install httpx"))).toBe(true);
  expect(evaluate(noPlainPip, bash("sudo pip install httpx"))).toBe(true);
});

test("allows uv and unrelated commands", () => {
  expect(evaluate(noPlainPip, bash("uv pip install httpx"))).toBe(false);
  expect(evaluate(noPlainPip, bash("poetry add httpx"))).toBe(false);
  expect(evaluate(noPlainPip, bash("ls -la"))).toBe(false);
});

test("tool mismatch makes the whole check false", () => {
  const asEdit: FactRecord = {
    toolName: "Edit",
    toolInput: { command: "pip install x" },
    permissionMode: "default",
  };
  expect(evaluate(noPlainPip, asEdit)).toBe(false);
});

test("an absent fact makes an atom false, not an error", () => {
  const check: Check = {
    op: "str.contains",
    field: { kind: "input", key: "command" },
    value: "pip",
  };
  const noCommand: FactRecord = {
    toolName: "Read",
    toolInput: { file_path: "/x" },
    permissionMode: "default",
  };
  expect(evaluate(check, noCommand)).toBe(false);
});

test("prefix, suffix, glob, enum, int atoms", () => {
  expect(
    evaluate({ op: "str.prefix", field: { kind: "input", key: "command" }, value: "git " }, bash("git push")),
  ).toBe(true);
  expect(
    evaluate({ op: "str.suffix", field: { kind: "path" }, value: ".env" }, bash("cat", { path: "/app/.env" })),
  ).toBe(true);
  expect(
    evaluate({ op: "path.glob", field: { kind: "path" }, glob: "src/**/*.ts" }, bash("edit", { path: "src/a/b.ts" })),
  ).toBe(true);
  expect(
    evaluate({ op: "enum.in", field: { kind: "permissionMode" }, values: ["bypassPermissions", "acceptEdits"] }, bash("x", { permissionMode: "plan" })),
  ).toBe(false);
  expect(
    evaluate({ op: "int.cmp", field: { kind: "input", key: "count" }, cmp: "ge", value: 3 }, { toolName: "T", toolInput: { count: 5 }, permissionMode: "default" }),
  ).toBe(true);
});

test("branch-conditioned rule (README Risk 2 example shape)", () => {
  const blockCommitToMain: Check = {
    op: "and",
    checks: [
      { op: "str.eq", field: { kind: "tool" }, value: "Bash" },
      { op: "str.contains", field: { kind: "input", key: "command" }, value: "git commit" },
      { op: "str.eq", field: { kind: "branch" }, value: "main" },
    ],
  };
  expect(evaluate(blockCommitToMain, bash("git commit -m x", { branch: "main" }))).toBe(true);
  expect(evaluate(blockCommitToMain, bash("git commit -m x", { branch: "feature" }))).toBe(false);
  // No branch resolved (solo scratch repo with no main): the rule does not fire.
  expect(evaluate(blockCommitToMain, bash("git commit -m x"))).toBe(false);
});

test("checkError flags a bad regex atom", () => {
  expect(checkError({ op: "str.regex", field: { kind: "tool" }, pattern: "a(b" })).not.toBeNull();
  expect(checkError(noPlainPip)).toBeNull();
});

test("checkError rejects a structurally malformed check", () => {
  // These arrive as untrusted JSON from a card; the union type cannot guard them.
  expect(checkError({ op: "totally-bogus", field: { kind: "tool" } } as unknown as Check)).toContain("unknown check op");
  expect(checkError({ op: "totally-bogus" } as unknown as Check)).not.toBeNull();
  expect(checkError({ op: "str.eq", value: "x" } as unknown as Check)).toContain("field");
  expect(checkError({ op: "str.eq", field: { kind: "bogus" }, value: "x" } as unknown as Check)).toContain("field kind");
  expect(checkError({ op: "int.cmp", field: { kind: "tool" }, cmp: "eq", value: 1 } as unknown as Check)).toContain("cmp");
  expect(checkError({ op: "str.in", field: { kind: "tool" }, values: "x" } as unknown as Check)).toContain("values");
  expect(checkError({ op: "input-no-key", field: { kind: "input" }, value: "x" } as unknown as Check)).not.toBeNull();
});

test("evaluate fails closed on a malformed atom, never throws or returns undefined", () => {
  const facts = bash("pip install x");
  expect(evaluate({ op: "bogus" } as unknown as Check, facts)).toBe(false);
  // missing field would throw if unguarded
  expect(evaluate({ op: "str.eq", value: "x" } as unknown as Check, facts)).toBe(false);
});
