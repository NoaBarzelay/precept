import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Entry, SCHEMA_VERSION } from "../../src/domain/entry.ts";
import { Index, sectionize } from "../../src/retrieve/index.ts";
import { budget, INJECTION_BOUNDS, retrieve } from "../../src/retrieve/retrieve.ts";
import { writeCard } from "../../src/store/card.ts";

let home: string;
let state: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  state = mkdtempSync(join(tmpdir(), "precept-state-"));
  process.env.PRECEPT_HOME = home;
  process.env.PRECEPT_STATE_DIR = state;
});

afterEach(() => {
  delete process.env.PRECEPT_HOME;
  delete process.env.PRECEPT_STATE_DIR;
  rmSync(home, { recursive: true, force: true });
  rmSync(state, { recursive: true, force: true });
});

function entry(over: Partial<Entry> & Pick<Entry, "id" | "content">): Entry {
  return {
    schemaVersion: SCHEMA_VERSION,
    version: 1,
    kind: "knowledge",
    scope: { kind: "global" },
    validity: { validFrom: "2026-07-19", condition: "always" },
    provenance: { signalKind: "stated-knowledge" },
    status: "active",
    ...over,
  } as Entry;
}

test("sectionize splits by heading, falls back to whole", () => {
  expect(sectionize("no headings here")).toEqual([{ anchor: "", text: "no headings here" }]);
  const s = sectionize("intro\n## Deploy\nRender\n## Auth\nJWT");
  expect(s.map((x) => x.anchor)).toEqual(["", "Deploy", "Auth"]);
});

test("retrieves a fact by relevance", () => {
  writeCard(entry({ id: "staging-on-render", content: "Staging runs on Render, prod is Fly.io." }));
  writeCard(entry({ id: "auth-uses-jwt", content: "Authentication uses JWT tokens." }));
  const idx = new Index();
  idx.rebuild();
  const hits = idx.search("where does staging run");
  idx.close();
  expect(hits.length).toBeGreaterThan(0);
  expect(hits[0]!.id).toBe("staging-on-render");
});

test("surfaces the applicable section of a long record (R2.7)", () => {
  writeCard(
    entry({
      id: "acme-infra",
      content: "# Infra\n## Deploy\nStaging on Render, prod on Fly.io.\n## Auth\nWe use JWT with refresh tokens.",
    }),
  );
  const idx = new Index();
  idx.rebuild();
  const hits = idx.search("jwt refresh token");
  idx.close();
  expect(hits[0]!.anchor).toBe("Auth");
  expect(hits[0]!.text).toContain("JWT");
  expect(hits[0]!.text).not.toContain("Render");
});

test("does not surface retired or expired entries (R2.8)", () => {
  writeCard(entry({ id: "old-fact", content: "Deploys go through Heroku.", status: "retired" }));
  writeCard(
    entry({
      id: "expired-fact",
      content: "Deploys go through Heroku classic.",
      validity: { validFrom: "2026-01-01", validUntil: "2026-06-01", condition: "x" },
    }),
  );
  const idx = new Index();
  idx.rebuild();
  const hits = idx.search("deploys heroku");
  idx.close();
  expect(hits).toEqual([]);
});

test("rebuild is deterministic and equal to incremental upsert", () => {
  writeCard(entry({ id: "a", content: "Staging runs on Render." }));
  writeCard(entry({ id: "b", content: "Prod runs on Fly.io." }));

  const idx1 = new Index(join(state, "one.db"));
  idx1.rebuild();
  const r1 = idx1.search("runs");
  idx1.close();

  const idx2 = new Index(join(state, "two.db"));
  idx2.upsert({ ...entry({ id: "a", content: "Staging runs on Render." }) });
  idx2.upsert({ ...entry({ id: "b", content: "Prod runs on Fly.io." }) });
  const r2 = idx2.search("runs");
  idx2.close();

  expect(r1.map((h) => h.id).sort()).toEqual(r2.map((h) => h.id).sort());
});

test("the injected slice stays bounded as the catalog grows (N9)", () => {
  for (let i = 0; i < 200; i++) {
    writeCard(entry({ id: `note-${i}`, content: `Deploy note number ${i} about the render service.` }));
  }
  const idx = new Index();
  idx.rebuild();
  const hits = budget(idx.search("render deploy", { limit: 8 }), { maxChars: 400 });
  idx.close();
  expect(hits.length).toBeLessThanOrEqual(8);
  const total = hits.reduce((n, h) => n + h.text.length, 0);
  expect(total).toBeLessThanOrEqual(400 + (hits[hits.length - 1]?.text.length ?? 0));
});

test("the default retrieve path meets the stated N9 caps (5 / 2000)", () => {
  const long = "Deploy detail. ".repeat(60); // ~900 chars each
  for (let i = 0; i < 30; i++) {
    writeCard(entry({ id: `note-${i}`, content: `Render deploy note ${i}. ${long}` }));
  }
  new Index().rebuild();
  const hits = retrieve("render deploy note");
  expect(hits.length).toBeLessThanOrEqual(INJECTION_BOUNDS.limit);
  expect(hits.length).toBeLessThanOrEqual(5);
  const total = hits.reduce((n, h) => n + h.text.length, 0);
  // stops once the cap is exceeded, so at most one entry spills over it
  expect(total).toBeLessThanOrEqual(INJECTION_BOUNDS.maxChars + long.length + 40);
});

test("budget truncates a single oversized section to the hard cap (N9)", () => {
  const huge = "render deploy detail ".repeat(500); // ~10k chars, one section
  writeCard(entry({ id: "big", content: huge }));
  new Index().rebuild();
  const hits = retrieve("render deploy", { maxChars: 200 });
  expect(hits.length).toBe(1);
  expect(hits[0]!.text.length).toBeLessThanOrEqual(200);
  expect(hits[0]!.text.endsWith("...")).toBe(true);
});

test("empty or symbol-only query returns nothing, no FTS syntax error", () => {
  writeCard(entry({ id: "x", content: "content here" }));
  const idx = new Index();
  idx.rebuild();
  expect(idx.search("")).toEqual([]);
  expect(idx.search("()*:")).toEqual([]);
  idx.close();
});
