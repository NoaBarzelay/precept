import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SCHEMA_VERSION, type Entry } from "../../src/domain/entry.ts";
import { Index } from "../../src/retrieve/index.ts";
import { assembleContext, GUARANTEED_SLOTS, retrieve } from "../../src/retrieve/retrieve.ts";
import { writeCard } from "../../src/store/card.ts";
import { readExternalNotes, writeNote } from "../../src/store/vault.ts";

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

/** Write one of Noa's own notes into the vault. */
function herNote(rel: string, front: string, body: string): void {
  const abs = join(vault, rel);
  mkdirSync(join(abs, ".."), { recursive: true });
  writeFileSync(abs, `---\n${front}\n---\n\n${body}\n`);
}

const entry = (over: Partial<Entry> = {}): Entry => ({
  schemaVersion: SCHEMA_VERSION,
  version: 1,
  id: "an-entry",
  kind: "convention",
  scope: { kind: "global" },
  status: "active",
  content: "Always cross-check the hazard rate against press releases.",
  validity: { validFrom: "2026-09-08", condition: "always" },
  provenance: { signalKind: "correction" },
  ...over,
});

test("her knowledge notes are read, her other files are not", () => {
  herNote("Career/Guide.md", "type: knowledge\ntitle: Hazard Models", "Discrete-time hazard modelling.");
  herNote("Personal/Diary.md", "type: note\ntitle: Diary", "Private writing about hazard.");
  herNote("Career/Untagged.md", "title: Loose", "No type at all, so hers.");

  const docs = readExternalNotes();
  expect(docs.map((d) => d.path)).toEqual(["Career/Guide.md"]);
  expect(docs[0]!.title).toBe("Hazard Models");
  expect(docs[0]!.content).toBe("Discrete-time hazard modelling."); // frontmatter stripped
});

test("the memory and transcript folders are excluded", () => {
  // Claude/ is already loaded into every session by CLAUDE.md, and Claude
  // Conversations/ is Precept's own past output.
  herNote("Claude/project thing.md", "type: knowledge\ntitle: Memory", "hazard hazard hazard");
  herNote("Claude Conversations/session.md", "type: knowledge\ntitle: Log", "hazard hazard");
  herNote("Career/Real.md", "type: knowledge\ntitle: Real", "hazard modelling");
  expect(readExternalNotes().map((d) => d.path)).toEqual(["Career/Real.md"]);
});

test("a Precept-written note is not double-indexed as an external doc", () => {
  writeNote(
    entry({ id: "precept-owned", kind: "knowledge", content: "## Owned\n\nA hazard fact." }),
    "Career",
    "2026-09-08",
  );
  expect(readExternalNotes()).toEqual([]);
});

test("her notes become retrievable, labelled as hers", () => {
  herNote(
    "Career/Wenrix.md",
    "type: knowledge\ntitle: Wenrix ML Prep",
    "## Censoring\n\nA censored booking is an observation that stopped, not a negative.",
  );
  const index = new Index();
  try {
    index.rebuild();
  } finally {
    index.close();
  }

  const hits = retrieve("censored booking observation stopped");
  expect(hits).not.toHaveLength(0);
  expect(hits[0]!.source).toBe("vault");
  expect(hits[0]!.id).toBe("Career/Wenrix.md");

  const context = assembleContext(hits);
  expect(context).toContain("[Noa's own note: Career/Wenrix.md");
  expect(context).not.toContain("(Career/Wenrix.md)"); // never rendered as a governed entry
});

test("governed entries are never crowded out by the vault", () => {
  // Many competing vault notes against one governed entry on the same topic.
  for (let i = 0; i < 20; i++) {
    herNote(`Career/Note${i}.md`, "type: knowledge\ntitle: N${i}", "hazard press releases cross-check");
  }
  writeCard(entry());
  const index = new Index();
  try {
    index.rebuild();
  } finally {
    index.close();
  }

  const hits = retrieve("hazard press releases cross-check");
  expect(hits.filter((h) => h.source === "precept").length).toBeGreaterThanOrEqual(
    GUARANTEED_SLOTS,
  );
});

test("the vault is not crowded out by governed entries either", () => {
  // Enough governed entries to fill every slot on their own.
  for (let i = 0; i < 10; i++) {
    writeCard(entry({ id: `entry-${i}`, content: "hazard press releases cross-check always" }));
  }
  herNote("Career/Deep.md", "type: knowledge\ntitle: Deep", "hazard press releases cross-check detail");
  const index = new Index();
  try {
    index.rebuild();
  } finally {
    index.close();
  }

  const hits = retrieve("hazard press releases cross-check");
  expect(hits.filter((h) => h.source === "vault").length).toBeGreaterThanOrEqual(1);
  expect(hits.length).toBe(5);
});

test("her notes are read-only: nothing here yields a writable entry", () => {
  herNote("Career/Guide.md", "type: knowledge\ntitle: Guide", "Some knowledge.");
  const docs = readExternalNotes();
  // An ExternalDoc has no id, version, status or validity, so it cannot reach
  // writeCard, retire, or any other lifecycle path even by mistake.
  expect(Object.keys(docs[0]!).sort()).toEqual(["content", "path", "title"]);
});

test("a far better vault hit outranks weak governed entries", () => {
  // The case that made the first design wrong: an entry that merely shares a
  // common word must not displace the section that actually answers the query.
  writeCard(entry({ id: "weak", content: "Always use a model when you can." }));
  herNote(
    "Career/Wenrix.md",
    "type: knowledge\ntitle: Wenrix",
    "## Censoring\n\nDiscrete-time hazard models treat a censored observation as stopped, not negative, unlike binary classification.",
  );
  const index = new Index();
  try {
    index.rebuild();
  } finally {
    index.close();
  }

  const hits = retrieve("discrete-time hazard models censored observation binary classification");
  expect(hits[0]!.source).toBe("vault");
  expect(hits[0]!.anchor).toBe("Censoring");
  // Ordered by score, so the character budget truncates the weakest, not the best.
  for (let i = 1; i < hits.length; i++) {
    expect(hits[i]!.score).toBeLessThanOrEqual(hits[i - 1]!.score);
  }
});
