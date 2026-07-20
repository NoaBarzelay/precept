import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Entry, SCHEMA_VERSION } from "../../src/domain/entry.ts";
import { parse, readCard, serialize, writeCard } from "../../src/store/card.ts";
import { cardPath } from "../../src/store/paths.ts";

let home: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "precept-cards-"));
  process.env.PRECEPT_HOME = home;
});

afterEach(() => {
  delete process.env.PRECEPT_HOME;
  rmSync(home, { recursive: true, force: true });
});

function knowledge(): Entry {
  return {
    schemaVersion: SCHEMA_VERSION,
    id: "staging-on-render",
    kind: "knowledge",
    scope: { kind: "repository", repository: "acme-api" },
    content: "Staging runs on Render, prod is Fly.io (app acme-api).",
    validity: { validFrom: "2026-07-19", condition: "always" },
    provenance: { signalKind: "stated-knowledge", quote: "fyi staging runs on Render" },
    status: "active",
  };
}

function hardRule(): Entry {
  return {
    schemaVersion: SCHEMA_VERSION,
    id: "uv-not-pip",
    kind: "rule",
    scope: { kind: "repository", repository: "acme-api" },
    content: "In a uv project, use uv, never plain pip.",
    validity: { validFrom: "2026-07-19", condition: "the project uses uv" },
    provenance: { signalKind: "correction" },
    status: "active",
    tier: "hard",
    lifecycle: "operational",
    confirmations: 3,
    check: { op: "str.contains", field: { kind: "input", key: "command" }, value: "pip install" },
  };
}

test("round-trips a knowledge entry through text", () => {
  const e = knowledge();
  expect(parse(serialize(e))).toEqual(e);
});

test("round-trips a hard rule with a check block", () => {
  const e = hardRule();
  const text = serialize(e);
  expect(text).toContain("```check");
  expect(parse(text)).toEqual(e);
});

test("the card has readable YAML frontmatter", () => {
  const text = serialize(knowledge());
  expect(text.startsWith("---\n")).toBe(true);
  expect(text).toContain("kind: knowledge");
  expect(text).toContain("repository: acme-api");
});

test("writeCard then readCard round-trips on disk", () => {
  const e = hardRule();
  const path = writeCard(e);
  expect(path).toBe(cardPath(e.id));
  expect(readCard(e.id)).toEqual(e);
});

test("the write is atomic: no temp file remains", () => {
  writeCard(knowledge());
  const text = readFileSync(cardPath("staging-on-render"), "utf8");
  expect(text).toContain("Staging runs on Render");
});

test("serialize refuses an invalid entry", () => {
  const bad = { ...knowledge(), id: "Bad Id" };
  expect(() => serialize(bad)).toThrow(/invalid/);
});

test("parse rejects a card that violates the contract", () => {
  const text = serialize(knowledge()).replace("kind: knowledge", "kind: bogus");
  expect(() => parse(text)).toThrow(/invalid card/);
});

test("parse rejects text with no frontmatter", () => {
  expect(() => parse("just prose, no frontmatter")).toThrow(/frontmatter/);
});
