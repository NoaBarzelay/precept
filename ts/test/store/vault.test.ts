import { expect, test } from "bun:test";
import { SCHEMA_VERSION, type Entry } from "../../src/domain/entry.ts";
import { parseNote, preceptIdOf, serializeNote, titleOf } from "../../src/store/vault.ts";

const entry = (over: Partial<Entry> = {}): Entry => ({
  schemaVersion: SCHEMA_VERSION,
  version: 1,
  id: "decode-is-memory-bound",
  kind: "knowledge",
  scope: { kind: "situation", name: "inference research" },
  status: "active",
  content:
    "## Why decode is memory-bound\n\nPrefill reads each weight matrix once and applies it to 128k vectors, about 15,790 FLOPs per byte. Decode applies it to one vector, about 0.12.",
  validity: { validFrom: "2026-08-31", condition: "always" },
  provenance: { signalKind: "stated-knowledge", quote: "decode is memory bound" },
  ...over,
});

test("a knowledge entry round-trips through the vault note format", () => {
  const original = entry();
  const back = parseNote(serializeNote(original, "2026-09-08"));
  expect(back).toEqual(original);
});

test("the note carries Noa's own frontmatter contract", () => {
  const text = serializeNote(entry(), "2026-09-08");
  expect(text).toContain("type: knowledge");
  expect(text).toContain("updated: 2026-09-08");
  expect(text).toContain("title: Why decode is memory-bound");
  expect(text).toContain("date: 2026-08-31");
  expect(text).toContain("topic: always");
  expect(text).toContain("## Sources");
});

test("sources name the evidence rather than inventing a citation", () => {
  const text = serializeNote(entry(), "2026-09-08");
  expect(text).toContain("Recorded by Precept from a stated-knowledge signal");
  expect(text).toContain('"decode is memory bound"');
  expect(text).not.toContain("http");
});

test("a note without a precept block is not Precept's to read", () => {
  // This is the guard that keeps Precept from adopting or rewriting the notes
  // Noa wrote herself.
  const hers = "---\ntype: knowledge\nupdated: 2026-05-28\ntitle: Keyboard\n---\n\nHer own analysis.\n";
  expect(() => parseNote(hers)).toThrow(/no `precept:` frontmatter block/);
  expect(preceptIdOf(hers)).toBeNull();
  expect(preceptIdOf(serializeNote(entry(), "2026-09-08"))).toBe("decode-is-memory-bound");
});

test("only knowledge takes the note format", () => {
  expect(() => serializeNote(entry({ kind: "convention" }), "2026-09-08")).toThrow(
    /only knowledge serializes as a vault note/,
  );
});

test("titles come from the heading, else the first sentence", () => {
  expect(titleOf("## FLOPs (Floating Point Operations)\n\nOne operation.")).toBe(
    "FLOPs (Floating Point Operations)",
  );
  expect(titleOf("**Decode is memory-bound.** Because the ratio collapses.")).toBe(
    "Decode is memory-bound",
  );
  // A filename cannot carry a path separator or a colon.
  expect(titleOf("## Inference vs Training: Interconnect / Packaging")).toBe(
    "Inference vs Training Interconnect Packaging",
  );
  expect(titleOf("x".repeat(200)).length).toBeLessThanOrEqual(70);
});

test("the body survives without the Sources section leaking into content", () => {
  const withSources = entry({ content: "A fact.\n\nAnother line." });
  const back = parseNote(serializeNote(withSources, "2026-09-08"));
  expect(back.content).toBe("A fact.\n\nAnother line.");
  expect(back.content).not.toContain("Sources");
});

// --- Placement and I/O -----------------------------------------------------

import { afterEach, beforeEach } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { folderError, readNote, rescanVault, writeNote } from "../../src/store/vault.ts";

let vault: string;
let state: string;
let home: string;

beforeEach(() => {
  // PRECEPT_HOME must be set too: anything reaching listEntryIds or allEntries
  // would otherwise read the real catalog on this machine.
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  process.env.PRECEPT_HOME = home;
  vault = mkdtempSync(join(tmpdir(), "precept-vault-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  process.env.PRECEPT_VAULT = vault;
  process.env.PRECEPT_STATE_DIR = state;
});

afterEach(() => {
  delete process.env.PRECEPT_VAULT;
  delete process.env.PRECEPT_STATE_DIR;
  delete process.env.PRECEPT_HOME;
  rmSync(home, { recursive: true, force: true });
  rmSync(vault, { recursive: true, force: true });
  rmSync(state, { recursive: true, force: true });
});

const FOLDER = "Career/Tech Industry Landscape/AI Infrastructure";

test("a note is written into its subject folder and reads back by id", () => {
  const e = entry();
  const path = writeNote(e, FOLDER, "2026-09-08");
  expect(path).toBe(join(vault, FOLDER, "Why decode is memory-bound.md"));
  expect(readNote(e.id)).toEqual(e);
});

test("a folder cannot escape the vault", () => {
  expect(folderError("../../etc")).toContain("relative path inside the vault");
  expect(folderError("/etc")).toContain("relative path inside the vault");
  expect(folderError("~/secrets")).toContain("relative path inside the vault");
  expect(folderError("Career/AI")).toBeNull();
  expect(() => writeNote(entry(), "../escape", "2026-09-08")).toThrow();
});

test("it refuses to overwrite a note Noa wrote herself", () => {
  // The title Precept derives may collide with one of her own files. Clobbering
  // her writing is the one failure this store must never have.
  mkdirSync(join(vault, FOLDER), { recursive: true });
  const collide = join(vault, FOLDER, "Why decode is memory-bound.md");
  writeFileSync(collide, "---\ntype: knowledge\ntitle: mine\n---\n\nNoa's own note.\n");

  expect(() => writeNote(entry(), FOLDER, "2026-09-08")).toThrow(
    /refusing to overwrite a note Precept did not write/,
  );
  expect(readFileSync(collide, "utf8")).toContain("Noa's own note.");
});

test("rewriting the same entry in place is allowed", () => {
  const e = entry();
  writeNote(e, FOLDER, "2026-09-08");
  const updated = { ...e, version: 2, content: e.content + "\n\nMore." };
  writeNote(updated, FOLDER, "2026-09-09");
  expect(readNote(e.id)?.version).toBe(2);
});

test("a rescan repairs the map after a note is moved in Obsidian", () => {
  const e = entry();
  const original = writeNote(e, FOLDER, "2026-09-08");

  // Simulate Noa reorganizing: move the note to a different subject folder.
  const moved = join(vault, "Career/Startups/AI Infrastructure", "Why decode is memory-bound.md");
  mkdirSync(join(vault, "Career/Startups/AI Infrastructure"), { recursive: true });
  writeFileSync(moved, readFileSync(original, "utf8"));
  rmSync(original);
  expect(readNote(e.id)).toBeUndefined(); // map is stale

  const found = rescanVault();
  expect(found.map((f) => f.id)).toEqual([e.id]);
  expect(readNote(e.id)).toEqual(e);
});

test("a rescan ignores Noa's own notes", () => {
  mkdirSync(join(vault, "Personal/Recipes"), { recursive: true });
  writeFileSync(
    join(vault, "Personal/Recipes/Challah.md"),
    "---\ntype: knowledge\nupdated: 2026-01-01\n---\n\nHer recipe.\n",
  );
  writeNote(entry(), FOLDER, "2026-09-08");
  expect(rescanVault().map((e) => e.id)).toEqual(["decode-is-memory-bound"]);
});

test("two near-identical candidates get distinct ids once knowledge lives in the vault", async () => {
  // Regression: id allocation used to probe the card path, but a knowledge
  // entry committed to the vault has no card, so the probe called a taken id
  // free and the second entry silently overwrote the first. Two candidates
  // sharing their first six words is the ordinary case, not a rare one.
  const { review } = await import("../../src/gate/gate.ts");
  const shared = {
    kind: "knowledge" as const,
    scope: { kind: "global" as const },
    condition: "always",
    signalKind: "stated-knowledge" as const,
  };

  const first = review(
    { ...shared, content: "Financial management and advisory for businesses, with hospitality expertise." },
    { action: "keep" },
    { folder: FOLDER },
  );
  const second = review(
    { ...shared, content: "Financial management and advisory for businesses across all sectors." },
    { action: "keep" },
    { folder: FOLDER },
  );

  expect(second.entry!.id).not.toBe(first.entry!.id);
  expect(readNote(first.entry!.id)?.content).toContain("hospitality expertise");
  expect(readNote(second.entry!.id)?.content).toContain("across all sectors");
  expect(rescanVault()).toHaveLength(2);
});

test("an explicit title resolves two entries that derive the same filename", () => {
  // These share their first 70 characters, so both derive the same title.
  const short = entry({
    id: "blurb",
    content: "Financial management and advisory for businesses with deep expertise in hospitality and restaurants.",
  });
  const long = entry({
    id: "blurb-2",
    content: "Financial management and advisory for businesses with deep expertise in hospitality and all other sectors.",
  });

  writeNote(short, "Career/Side Hustle", "2026-09-08");
  // Without a title the second collides, which is the guard working, not a bug.
  expect(() => writeNote(long, "Career/Side Hustle", "2026-09-08")).toThrow(
    /title collides with a different Precept note/,
  );

  const path = writeNote(long, "Career/Side Hustle", "2026-09-08", "Service blurb (all sectors)");
  expect(path).toContain("Service blurb (all sectors).md");
  expect(readNote("blurb")?.content).toContain("hospitality and restaurants");
  expect(readNote("blurb-2")?.content).toContain("all other sectors");
});

test("a vault note is retrievable, not just stored", async () => {
  // Regression: the index rebuilt by listing the card directory, so once
  // knowledge moved to the vault every fact was stored and none was findable.
  const { Index } = await import("../../src/retrieve/index.ts");
  writeNote(entry(), FOLDER, "2026-09-08");

  const index = new Index();
  try {
    index.rebuild();
    const hits = index.search("decode memory bound FLOPs");
    expect(hits.map((h) => h.id)).toContain("decode-is-memory-bound");
  } finally {
    index.close();
  }
});

test("a lifecycle write keeps a vault entry in the vault", async () => {
  // Regression: retire/supersede/confirm call writeCard with no folder. Without
  // remembering where the note already lives, each of those would write a
  // second copy as a card and leave one id with two homes.
  const { writeCard, listEntryIds } = await import("../../src/store/card.ts");
  const e = entry();
  const path = writeNote(e, FOLDER, "2026-09-08");

  writeCard({ ...e, version: 2, status: "retired" });

  expect(listEntryIds()).toEqual([e.id]); // one home, not two
  expect(existsSync(join(home, "entries", `${e.id}.md`))).toBe(false);
  expect(readFileSync(path, "utf8")).toContain("status: retired");
});

test("a title containing a path separator cannot create a directory", () => {
  // Regression: the explicit title "The Hq/Hkv identity is already published"
  // made a folder called "The Hq" in the vault. titleOf already strips these
  // from derived titles; an explicit one is held to the same rule.
  const path = writeNote(entry(), FOLDER, "2026-09-09", "The Hq/Hkv identity is published");
  expect(path).toBe(join(vault, FOLDER, "The Hq Hkv identity is published.md"));
  expect(existsSync(join(vault, FOLDER, "The Hq"))).toBe(false);
  expect(readFileSync(path, "utf8")).toContain("title: The Hq Hkv identity is published");
});

test("a title that is only separators still yields a file", () => {
  const path = writeNote(entry({ id: "odd" }), FOLDER, "2026-09-09", "///");
  expect(path).toBe(join(vault, FOLDER, "untitled.md"));
});
