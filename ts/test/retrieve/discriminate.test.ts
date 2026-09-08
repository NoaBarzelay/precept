import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { discriminatingTokens, Index, RARITY_FACTOR } from "../../src/retrieve/index.ts";

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

function herNote(rel: string, body: string): void {
  const abs = join(vault, rel);
  mkdirSync(join(abs, ".."), { recursive: true });
  writeFileSync(abs, `---\ntype: knowledge\ntitle: ${rel}\n---\n\n${body}\n`);
}

// --- the selection rule, in isolation -------------------------------------

test("a token far more common than the rarest is dropped", () => {
  const df = new Map([["periodic", 107], ["automatic", 119], ["reindex", 3]]);
  expect(discriminatingTokens(df)).toEqual(["reindex"]);
});

test("comparably rare tokens are all kept, rarest first", () => {
  const df = new Map([["hazard", 20], ["censored", 15], ["survival", 25]]);
  expect(discriminatingTokens(df)).toEqual(["censored", "hazard", "survival"]);
});

test("rarity is relative, so uniformly common tokens are all kept", () => {
  // Nothing here discriminates against anything else, so narrowing would be
  // arbitrary. The query must still run rather than return nothing.
  const df = new Map([["model", 800], ["data", 900]]);
  expect(discriminatingTokens(df)).toEqual(["model", "data"]);
});

test("the rarest token always survives, so a query never empties", () => {
  // Even when every token is common in absolute terms, one that is an order of
  // magnitude rarer than the rest is the one carrying the signal.
  const df = new Map([["model", 800], ["data", 900], ["calibration", 40]]);
  expect(discriminatingTokens(df)).toEqual(["calibration"]);
});

test("the boundary is inclusive at exactly the factor", () => {
  const df = new Map([["rare", 5], ["edge", 5 * RARITY_FACTOR], ["over", 5 * RARITY_FACTOR + 1]]);
  expect(discriminatingTokens(df)).toEqual(["rare", "edge"]);
});

// --- end to end against a real index --------------------------------------

test("the rare term wins over two common ones (the reindex case)", () => {
  // Reconstructs the shape of the real failure: many short sections carrying a
  // common word, one long section carrying the rare word that identifies it.
  for (let i = 0; i < 30; i++) {
    herNote(`Noise/N${i}.md`, `## Policy\n\nEnforce standards automatically over a period.`);
  }
  herNote(
    "Precept/Build.md",
    `## Build progress\n\n${"Filler prose about the platform. ".repeat(60)}\nThe reindex step runs periodically; reindex is incremental; reindex is cheap; reindex again.`,
  );

  const index = new Index();
  try {
    index.rebuild();
    const hits = index.search("do a periodic automatic reindex", { limit: 5 });
    expect(hits[0]!.id).toBe("Precept/Build.md");
    // The noise sections must not merely rank lower, they must not match at
    // all: "periodic" and "automatic" are no longer asked about.
    expect(hits.every((h) => !h.id.startsWith("Noise/"))).toBe(true);
  } finally {
    index.close();
  }
});

test("a query of only common words still returns its best match", () => {
  for (let i = 0; i < 12; i++) herNote(`Noise/N${i}.md`, "Enforce standards automatically.");
  const index = new Index();
  try {
    index.rebuild();
    expect(index.search("automatically", { limit: 5 }).length).toBeGreaterThan(0);
  } finally {
    index.close();
  }
});

test("a token matching nothing does not starve the query", () => {
  // A typo or an unseen word has zero document frequency. It must be dropped
  // rather than becoming a rarest count of zero that rejects everything.
  herNote("A.md", "Discrete-time hazard models handle censoring.");
  const index = new Index();
  try {
    index.rebuild();
    const hits = index.search("hazard censoring zzzzqqq", { limit: 5 });
    expect(hits[0]!.id).toBe("A.md");
    expect(index.search("zzzzqqq wwwwvvv", { limit: 5 })).toEqual([]);
  } finally {
    index.close();
  }
});
