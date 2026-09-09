import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { keepCmd } from "../../src/cli.ts";
import type { Candidate } from "../../src/domain/candidate.ts";
import { enqueue } from "../../src/record/queue.ts";
import { allEntries } from "../../src/store/card.ts";
import { readVaultMap } from "../../src/store/vault.ts";

let vault: string;
let state: string;
let home: string;

beforeEach(() => {
  vault = mkdtempSync(join(tmpdir(), "precept-vault-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  process.env.PRECEPT_VAULT = vault;
  process.env.PRECEPT_STATE_DIR = state;
  process.env.PRECEPT_HOME = home;
});

afterEach(() => {
  delete process.env.PRECEPT_VAULT;
  delete process.env.PRECEPT_STATE_DIR;
  delete process.env.PRECEPT_HOME;
  for (const d of [vault, state, home]) rmSync(d, { recursive: true, force: true });
});

/** The detector's typical mistake: a rule proposed as knowledge. */
const rule: Candidate = {
  kind: "knowledge",
  scope: { kind: "situation", name: "VCC events" },
  content: "The tracker should include Speaker Name, Sector, Status and Owner.",
  condition: "when building the events tracker",
  signalKind: "instruction",
};

test("without an override a rule typed as knowledge lands in the vault", () => {
  const p = enqueue(rule);
  keepCmd(p.id, "CBS/Club Events");
  expect(Object.keys(readVaultMap())).toHaveLength(1);
  expect(allEntries()[0]!.kind).toBe("knowledge");
});

test("--kind convention keeps it a card, out of the vault", () => {
  const p = enqueue(rule);
  const out = keepCmd(p.id, "CBS/Club Events", undefined, "convention");
  expect(out).toContain("convention");
  expect(readVaultMap()).toEqual({}); // nothing written into Noa's Second Brain
  const entries = allEntries();
  expect(entries).toHaveLength(1);
  expect(entries[0]!.kind).toBe("convention");
  expect(existsSync(join(home, "entries", `${entries[0]!.id}.md`))).toBe(true);
});

test("an unknown kind is refused rather than silently ignored", () => {
  const p = enqueue(rule);
  const out = keepCmd(p.id, "CBS/Club Events", undefined, "guideline");
  expect(out).toContain("unknown kind 'guideline'");
  expect(allEntries()).toHaveLength(0); // nothing committed
});
