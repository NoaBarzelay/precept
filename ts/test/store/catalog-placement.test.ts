import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { cardPath, entriesDir } from "../../src/store/paths.ts";

let vault: string;

beforeEach(() => {
  vault = mkdtempSync(join(tmpdir(), "precept-vault-"));
});

afterEach(() => {
  delete process.env.PRECEPT_VAULT;
  delete process.env.PRECEPT_HOME;
  rmSync(vault, { recursive: true, force: true });
});

test("with a vault, rules are filed under its Claude folder", () => {
  // Noa's rule: anything that instructs Claude lives under Claude/, never in a
  // subject folder among her research and never outside the vault.
  process.env.PRECEPT_VAULT = vault;
  expect(entriesDir()).toBe(join(vault, "Claude", "Precept"));
  expect(cardPath("a-rule")).toBe(join(vault, "Claude", "Precept", "a-rule.md"));
});

test("PRECEPT_HOME still wins, so tests stay hermetic", () => {
  process.env.PRECEPT_VAULT = vault;
  process.env.PRECEPT_HOME = "/tmp/elsewhere";
  expect(entriesDir()).toBe(join("/tmp/elsewhere", "entries"));
});

test("with no vault it falls back, so the system runs unconfigured", () => {
  expect(entriesDir()).toContain(".precept");
});
