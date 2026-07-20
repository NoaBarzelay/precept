import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runCli } from "../src/cli.ts";
import { cardPath } from "../src/store/paths.ts";

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

test("note records a fact, recall retrieves it, list shows it", () => {
  const noted = runCli(["note", "Staging runs on Render, prod is Fly.io", "--repo", "acme-api"]);
  expect(noted).toMatch(/^noted /);
  const id = noted.slice("noted ".length);
  expect(existsSync(cardPath(id))).toBe(true);

  expect(runCli(["recall", "where does staging run"])).toContain("Render");
  const listed = runCli(["list"]);
  expect(listed).toContain(id);
  expect(listed).toContain("knowledge");
  expect(listed).toContain("repository:acme-api");
});

test("recall on an empty catalog says nothing relevant", () => {
  expect(runCli(["recall", "anything"])).toBe("(nothing relevant)");
});

test("list on an empty catalog says so", () => {
  expect(runCli(["list"])).toBe("(catalog is empty)");
});

test("remove deletes the card and drops it from retrieval (R1.16)", () => {
  const id = runCli(["note", "Deploys go through Heroku", "--global"]).slice("noted ".length);
  expect(existsSync(cardPath(id))).toBe(true);
  expect(runCli(["remove", id])).toBe(`removed ${id}`);
  expect(existsSync(cardPath(id))).toBe(false);
  expect(runCli(["recall", "heroku deploys"])).toBe("(nothing relevant)");
});

test("remove of a missing id is reported, not thrown", () => {
  expect(runCli(["remove", "no-such"])).toBe("no such entry: no-such");
});

test("reindex rebuilds from the cards", () => {
  runCli(["note", "Prod runs on Fly.io", "--repo", "acme-api"]);
  expect(runCli(["reindex"])).toBe("reindexed 1 entries");
});

test("unknown command prints help", () => {
  expect(runCli(["frobnicate"])).toContain("commands:");
});

test("note without content prints usage", () => {
  expect(runCli(["note"])).toContain("usage:");
});
