import { expect, test } from "bun:test";
import {
  assembleEvidence,
  parseTranscript,
} from "../../src/host/transcript.ts";

// A transcript line factory in the host's own JSONL shape.
const userLine = (text: string, extra: Record<string, unknown> = {}) =>
  JSON.stringify({
    type: "user",
    timestamp: "2026-07-20T10:00:00Z",
    message: { role: "user", content: text },
    ...extra,
  });

const toolResultLine = () =>
  JSON.stringify({
    type: "user",
    message: {
      role: "user",
      content: [{ type: "tool_result", tool_use_id: "x", content: "ok" }],
    },
  });

const assistantText = (text: string) =>
  JSON.stringify({
    type: "assistant",
    timestamp: "2026-07-20T10:00:01Z",
    message: { role: "assistant", content: [{ type: "text", text }] },
  });

const writeLine = (path: string, content: string) =>
  JSON.stringify({
    type: "assistant",
    timestamp: "2026-07-20T10:00:02Z",
    message: {
      role: "assistant",
      content: [
        { type: "tool_use", name: "Write", input: { file_path: path, content } },
      ],
    },
  });

const editLine = (path: string, newString: string) =>
  JSON.stringify({
    type: "assistant",
    message: {
      role: "assistant",
      content: [
        {
          type: "tool_use",
          name: "Edit",
          input: { file_path: path, old_string: "a", new_string: newString },
        },
      ],
    },
  });

const jsonl = (...lines: string[]) => lines.join("\n");

test("parse narrows roles, tool results, and file writes", () => {
  const raw = jsonl(
    userLine("use pnpm not npm"),
    toolResultLine(),
    assistantText("Got it."),
    writeLine("/work/a.ts", "export const a = 1;\n"),
  );
  const entries = parseTranscript(raw);
  expect(entries).toHaveLength(4);
  expect(entries[0]!.humanTyped).toBe(true);
  expect(entries[1]!.humanTyped).toBe(false); // a tool result is not human-typed
  expect(entries[2]!.role).toBe("assistant");
  expect(entries[3]!.writes[0]!.path).toBe("/work/a.ts");
  expect(entries[3]!.writes[0]!.kind).toBe("full");
  expect(entries[3]!.writes[0]!.outputs).toEqual(["export const a = 1;\n"]);
});

test("a torn line is skipped, not thrown", () => {
  const raw = jsonl(userLine("hello"), "{not valid json", assistantText("hi"));
  const entries = parseTranscript(raw);
  expect(entries).toHaveLength(2);
});

test("provenance gate: only human-typed turns become evidence", () => {
  const raw = jsonl(
    userLine("always run the tests before committing"),
    toolResultLine(),
    assistantText("Understood."),
  );
  const evidence = assembleEvidence(raw, { session: "s1" });
  expect(evidence).toHaveLength(1);
  expect(evidence[0]!.signalKind).toBe("instruction");
  expect(evidence[0]!.session).toBe("s1");
});

test("a subagent (sidechain) user turn is not human-typed", () => {
  const raw = jsonl(userLine("do the thing", { isSidechain: true }));
  const evidence = assembleEvidence(raw, { session: "s1" });
  expect(evidence).toHaveLength(0);
});

test("correction cues tag the signal kind", () => {
  const raw = jsonl(userLine("no, don't use httpx, use requests"));
  const evidence = assembleEvidence(raw, { session: "s1" });
  expect(evidence[0]!.signalKind).toBe("correction");
});

test("evidence carries a verbatim window of the surrounding turns (R1.1)", () => {
  const raw = jsonl(
    userLine("add a health endpoint"),
    assistantText("Added GET /health returning 200."),
    userLine("no, it should return the build sha too"),
  );
  const evidence = assembleEvidence(raw, { session: "s1" });
  const correction = evidence.at(-1)!;
  // The window holds the earlier turns verbatim, not just the final turn.
  expect(correction.turns).toContain("add a health endpoint");
  expect(correction.turns).toContain("Added GET /health");
  expect(correction.turns).toContain("build sha");
});

test("silent edit: disk state diverging from the agent's output is evidence", () => {
  const raw = jsonl(
    userLine("write the config"),
    writeLine("/work/config.ts", "export const port = 3000;\n"),
  );
  const disk = new Map([["/work/config.ts", "export const port = 8080;\n"]]);
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: (p) => disk.get(p),
  });
  const edit = evidence.find((e) => e.signalKind === "silent-edit")!;
  expect(edit).toBeDefined();
  expect(edit.agentOutput).toBe("export const port = 3000;\n");
  expect(edit.finalState).toBe("export const port = 8080;\n");
});

test("no silent-edit signal when the file is unchanged", () => {
  const raw = jsonl(writeLine("/work/a.ts", "same\n"));
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => "same\n",
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(0);
});

test("no silent-edit signal when the file cannot be read", () => {
  const raw = jsonl(writeLine("/work/gone.ts", "content\n"));
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => undefined,
  });
  expect(evidence).toHaveLength(0);
});

test("an Edit is diffed by fragment presence, not equality (no false positive)", () => {
  // The agent added three lines by Edit; the user changed nothing else. The
  // fragment is still in the (larger) file, so there is no silent edit. This is
  // the regression for the fragment-vs-whole-file bug: equality would have fired.
  const raw = jsonl(editLine("/work/app.ts", "  return envelope(data);\n"));
  const disk = "export function handler() {\n  return envelope(data);\n}\n";
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => disk,
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(0);
});

test("an Edit whose fragment the user removed is a silent edit", () => {
  const raw = jsonl(editLine("/work/app.ts", "  return rawDict;\n"));
  const disk = "export function handler() {\n  return envelope(data);\n}\n";
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => disk, // the agent's line is gone: user rewrote it
  });
  const edit = evidence.find((e) => e.signalKind === "silent-edit")!;
  expect(edit).toBeDefined();
  expect(edit.agentOutput).toBe("  return rawDict;\n");
  expect(edit.finalState).toBe(disk);
});

test("MultiEdit is diffed, not silently dropped", () => {
  const multi = JSON.stringify({
    type: "assistant",
    message: {
      role: "assistant",
      content: [
        {
          type: "tool_use",
          name: "MultiEdit",
          input: {
            file_path: "/work/m.ts",
            edits: [
              { old_string: "a", new_string: "kept line\n" },
              { old_string: "b", new_string: "removed line\n" },
            ],
          },
        },
      ],
    },
  });
  // One fragment survives, one was removed: any missing fragment is a signal.
  const evidence = assembleEvidence(multi, { session: "s1" }, {
    readFinalState: () => "kept line\n",
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(1);
});

test("a full Write matching disk yields no silent edit; the last write wins", () => {
  const raw = jsonl(
    writeLine("/work/a.ts", "v1\n"),
    writeLine("/work/a.ts", "v2\n"),
  );
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => "v2\n", // matches the last full write: no silent edit
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(0);
});

test("same-basename files in one turn do not collide (distinct ids)", () => {
  const twoWrites = JSON.stringify({
    type: "assistant",
    message: {
      role: "assistant",
      content: [
        { type: "tool_use", name: "Write", input: { file_path: "/work/src/index.ts", content: "a\n" } },
        { type: "tool_use", name: "Write", input: { file_path: "/work/test/index.ts", content: "b\n" } },
      ],
    },
  });
  const disk = new Map([
    ["/work/src/index.ts", "changed-a\n"],
    ["/work/test/index.ts", "changed-b\n"],
  ]);
  const evidence = assembleEvidence(twoWrites, { session: "s1" }, {
    readFinalState: (p) => disk.get(p),
  });
  const edits = evidence.filter((e) => e.signalKind === "silent-edit");
  expect(edits).toHaveLength(2);
  expect(new Set(edits.map((e) => e.id)).size).toBe(2);
});

test("re-processing a grown transcript yields stable ids for old turns", () => {
  // Idempotency comes from content-derived ids + caller dedup, not a cursor: an
  // unchanged turn keeps its id when the transcript grows, so the caller drops
  // it and appends only the genuinely new turn.
  const first = assembleEvidence(jsonl(userLine("first instruction")), { session: "s1" });
  const grown = assembleEvidence(
    jsonl(userLine("first instruction"), userLine("second instruction")),
    { session: "s1" },
  );
  expect(grown).toHaveLength(2);
  expect(grown[0]!.id).toBe(first[0]!.id); // unchanged turn: same id
  const fresh = grown.filter((e) => !first.some((f) => f.id === e.id));
  expect(fresh).toHaveLength(1);
  expect(fresh[0]!.turns).toContain("second instruction");
});

test("evidence ids are stable across runs, for dedup", () => {
  const raw = jsonl(userLine("stable"));
  const a = assembleEvidence(raw, { session: "s1" });
  const b = assembleEvidence(raw, { session: "s1" });
  expect(a[0]!.id).toBe(b[0]!.id);
});

test("ids are position-independent, so a compacted transcript re-dedups", () => {
  // The same turn (with the same window) keeps its id even after earlier
  // entries are dropped, so re-processing a rotated transcript from zero dedups
  // the unchanged turn instead of re-emitting it under a shifted index.
  const before = assembleEvidence(jsonl(userLine("keep this instruction")), {
    session: "s1",
  });
  // The transcript was compacted: a leading marker line was removed, but the
  // human turn and its (empty) preceding window are unchanged.
  const after = assembleEvidence(
    jsonl(JSON.stringify({ type: "system", subtype: "compact" }), userLine("keep this instruction")),
    { session: "s1" },
  );
  expect(after[0]!.id).toBe(before[0]!.id);
});

test("a turn keyed on message.role is captured even without a top-level type", () => {
  const raw = JSON.stringify({ message: { role: "user", content: "no type field here" } });
  const evidence = assembleEvidence(raw, { session: "s1" });
  expect(evidence).toHaveLength(1);
  expect(evidence[0]!.turns).toContain("no type field here");
});

test("a huge silent-edit payload is capped", () => {
  const big = "x".repeat(50_000);
  const raw = jsonl(writeLine("/work/big.ts", big));
  const evidence = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => `${big}changed`,
  });
  const edit = evidence.find((e) => e.signalKind === "silent-edit")!;
  expect(edit.agentOutput!.length).toBeLessThan(big.length);
  expect(edit.agentOutput).toContain("[...truncated]");
});

test("repository falls back to the entry's cwd basename", () => {
  const raw = jsonl(userLine("scoped", { cwd: "/work/acme-api" }));
  const evidence = assembleEvidence(raw, { session: "s1" });
  expect(evidence[0]!.repository).toBe("acme-api");
});
