import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Index } from "../../src/retrieve/index.ts";
import { retrieve } from "../../src/retrieve/retrieve.ts";
import { shouldRefreshIndex, stampRefreshed } from "../../src/record/refresh.ts";
import { refreshStampPath, vaultManifestPath } from "../../src/store/paths.ts";

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
  delete process.env.PRECEPT_REFRESH_INTERVAL_MINUTES;
  for (const d of [vault, state, home]) rmSync(d, { recursive: true, force: true });
});

function herNote(rel: string, title: string, body: string): void {
  const abs = join(vault, rel);
  mkdirSync(join(abs, ".."), { recursive: true });
  writeFileSync(abs, `---\ntype: knowledge\ntitle: ${title}\n---\n\n${body}\n`);
}

/** Force a distinct mtime, since a test can rewrite a file within one tick. */
function touch(rel: string, secondsAhead: number): void {
  const abs = join(vault, rel);
  const t = new Date(Date.now() + secondsAhead * 1000);
  utimesSync(abs, t, t);
}

function withIndex<T>(fn: (i: Index) => T): T {
  const index = new Index();
  try {
    return fn(index);
  } finally {
    index.close();
  }
}

test("a first refresh indexes everything and records a manifest", () => {
  herNote("Career/A.md", "A", "hazard modelling of censored data");
  herNote("Career/B.md", "B", "unrelated content about baking");

  const result = withIndex((i) => i.refresh());
  expect(result).toEqual({ added: 2, updated: 0, removed: 0, unchanged: 0 });
  expect(existsSync(vaultManifestPath())).toBe(true);
  expect(retrieve("hazard censored")[0]!.id).toBe("Career/A.md");
});

test("a second refresh with nothing changed reads no bodies", () => {
  herNote("Career/A.md", "A", "hazard modelling");
  withIndex((i) => i.refresh());
  expect(withIndex((i) => i.refresh())).toEqual({
    added: 0,
    updated: 0,
    removed: 0,
    unchanged: 1,
  });
});

test("an edited note is re-indexed and the old text stops matching", () => {
  herNote("Career/A.md", "A", "the original text mentions hazard");
  withIndex((i) => i.refresh());
  expect(retrieve("hazard")).not.toHaveLength(0);

  herNote("Career/A.md", "A", "rewritten to discuss calibration instead");
  touch("Career/A.md", 10);
  expect(withIndex((i) => i.refresh()).updated).toBe(1);

  expect(retrieve("hazard")).toHaveLength(0);
  expect(retrieve("calibration")).not.toHaveLength(0);
});

test("a deleted note leaves the index", () => {
  herNote("Career/A.md", "A", "hazard modelling");
  withIndex((i) => i.refresh());
  rmSync(join(vault, "Career/A.md"));

  expect(withIndex((i) => i.refresh()).removed).toBe(1);
  expect(retrieve("hazard")).toHaveLength(0);
});

test("a note retyped away from knowledge leaves the index", () => {
  // Retagging as `type: note` reclaims it as hers to write, not knowledge.
  herNote("Career/A.md", "A", "hazard modelling");
  withIndex((i) => i.refresh());
  writeFileSync(join(vault, "Career/A.md"), "---\ntype: note\n---\n\nhazard modelling\n");
  touch("Career/A.md", 10);

  expect(withIndex((i) => i.refresh()).removed).toBe(1);
  expect(retrieve("hazard")).toHaveLength(0);
});

test("the throttle holds between refreshes and releases after the interval", () => {
  process.env.PRECEPT_REFRESH_INTERVAL_MINUTES = "30";
  const now = new Date("2026-09-08T10:00:00Z");
  expect(shouldRefreshIndex(now)).toBe(true); // no stamp yet
  stampRefreshed(now);
  expect(existsSync(refreshStampPath())).toBe(true);

  expect(shouldRefreshIndex(new Date("2026-09-08T10:20:00Z"))).toBe(false);
  expect(shouldRefreshIndex(new Date("2026-09-08T10:31:00Z"))).toBe(true);
});

test("zero disables the throttle, and the subprocess sentinel disables refresh", () => {
  process.env.PRECEPT_REFRESH_INTERVAL_MINUTES = "0";
  stampRefreshed(new Date());
  expect(shouldRefreshIndex()).toBe(true);

  process.env.PRECEPT_INFERENCE_SUBPROCESS = "1";
  try {
    expect(shouldRefreshIndex()).toBe(false);
  } finally {
    delete process.env.PRECEPT_INFERENCE_SUBPROCESS;
  }
});

test("refresh does not disturb the governed entries in the index", () => {
  const { writeCard } = require("../../src/store/card.ts");
  writeCard({
    schemaVersion: 1,
    version: 1,
    id: "an-entry",
    kind: "convention",
    scope: { kind: "global" },
    status: "active",
    content: "Cross-check the hazard rate against press releases.",
    validity: { validFrom: "2026-09-08", condition: "always" },
    provenance: { signalKind: "correction" },
  });
  withIndex((i) => i.rebuild());
  expect(retrieve("press releases").some((h) => h.source === "precept")).toBe(true);

  herNote("Career/A.md", "A", "something else entirely");
  withIndex((i) => i.refresh());
  expect(retrieve("press releases").some((h) => h.source === "precept")).toBe(true);
});
