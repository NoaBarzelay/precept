import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  keepCmd,
  listCmd,
  noteCmd,
  pendingCmd,
  recallCmd,
  retireCmd,
  supersedeCmd,
} from "../src/cli.ts";
import { enqueue } from "../src/record/queue.ts";
import { readCard } from "../src/store/card.ts";

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

test("retire invalidates an entry: gone from recall, kept on disk as retired", () => {
  const out = noteCmd(["staging", "runs", "on", "Render"]);
  const id = out.replace("noted ", "");
  expect(recallCmd(["where", "does", "staging", "run"]).length).toBeGreaterThan(0);

  expect(retireCmd(id)).toBe(`retired ${id}`);
  expect(recallCmd(["where", "does", "staging", "run"])).toBe("(nothing relevant)");
  // Invalidate-not-delete: the card is still there, marked retired.
  expect(readCard(id).status).toBe("retired");
  expect(listCmd()).toContain("retired");
});

test("retire is reported, not thrown, on an unknown or already-retired entry", () => {
  expect(retireCmd("nope")).toBe("no such entry: nope");
  const id = noteCmd(["a", "durable", "fact"]).replace("noted ", "");
  retireCmd(id);
  expect(retireCmd(id)).toBe(`${id} is already retired`);
});

test("supersede folds an old entry over a new one, recording the pointer", () => {
  const oldId = noteCmd(["use", "npm", "for", "this"]).replace("noted ", "");
  const newId = noteCmd(["use", "pnpm", "for", "this"]).replace("noted ", "");
  expect(supersedeCmd([oldId, newId])).toBe(`superseded ${oldId} by ${newId}`);
  const older = readCard(oldId);
  expect(older.status).toBe("superseded");
  expect(older.supersededBy).toBe(newId);
  // The superseded entry no longer surfaces; the successor still does.
  expect(recallCmd(["npm"])).not.toContain(oldId);
});

test("supersede reports a missing successor rather than committing", () => {
  const oldId = noteCmd(["something", "durable"]).replace("noted ", "");
  expect(supersedeCmd([oldId, "ghost"])).toBe("no such successor: ghost");
  expect(readCard(oldId).status).toBe("active"); // untouched
});

test("review surfaces a near-duplicate so the reviewer can supersede it", () => {
  const dup = {
    kind: "convention" as const,
    scope: { kind: "global" as const },
    content: "always run the tests before committing",
    condition: "always",
    signalKind: "instruction" as const,
  };
  // Commit the first convention, then queue a duplicate of it.
  enqueue(dup);
  keepCmd(pendingCmd().split(" ")[0]!);
  enqueue(dup);

  expect(pendingCmd()).toContain("may duplicate");
  const pendingId = pendingCmd().split(" ")[0]!;
  expect(keepCmd(pendingId)).toContain("may duplicate");
});

test("review does not flag a different-kind entry as a duplicate", () => {
  // A knowledge fact and a convention with the same words are not duplicates.
  noteCmd(["always", "prefer", "pnpm", "here"]); // knowledge
  enqueue({
    kind: "convention",
    scope: { kind: "global" },
    content: "always prefer pnpm here",
    condition: "always",
    signalKind: "instruction",
  });
  expect(pendingCmd()).not.toContain("may duplicate");
});
