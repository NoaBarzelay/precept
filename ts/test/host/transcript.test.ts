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
  expect(entries[3]!.writes[0]!.agentOutput).toBe("export const a = 1;\n");
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
  const { evidence } = assembleEvidence(raw, { session: "s1" });
  expect(evidence).toHaveLength(1);
  expect(evidence[0]!.signalKind).toBe("instruction");
  expect(evidence[0]!.session).toBe("s1");
});

test("a subagent (sidechain) user turn is not human-typed", () => {
  const raw = jsonl(userLine("do the thing", { isSidechain: true }));
  const { evidence } = assembleEvidence(raw, { session: "s1" });
  expect(evidence).toHaveLength(0);
});

test("correction cues tag the signal kind", () => {
  const raw = jsonl(userLine("no, don't use httpx, use requests"));
  const { evidence } = assembleEvidence(raw, { session: "s1" });
  expect(evidence[0]!.signalKind).toBe("correction");
});

test("evidence carries a verbatim window of the surrounding turns (R1.1)", () => {
  const raw = jsonl(
    userLine("add a health endpoint"),
    assistantText("Added GET /health returning 200."),
    userLine("no, it should return the build sha too"),
  );
  const { evidence } = assembleEvidence(raw, { session: "s1" });
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
  const { evidence } = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: (p) => disk.get(p),
  });
  const edit = evidence.find((e) => e.signalKind === "silent-edit")!;
  expect(edit).toBeDefined();
  expect(edit.agentOutput).toBe("export const port = 3000;\n");
  expect(edit.finalState).toBe("export const port = 8080;\n");
});

test("no silent-edit signal when the file is unchanged", () => {
  const raw = jsonl(writeLine("/work/a.ts", "same\n"));
  const { evidence } = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => "same\n",
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(0);
});

test("no silent-edit signal when the file cannot be read", () => {
  const raw = jsonl(writeLine("/work/gone.ts", "content\n"));
  const { evidence } = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => undefined,
  });
  expect(evidence).toHaveLength(0);
});

test("only the agent's LAST write to a path is diffed", () => {
  const raw = jsonl(
    writeLine("/work/a.ts", "v1\n"),
    editLine("/work/a.ts", "v2\n"),
  );
  const { evidence } = assembleEvidence(raw, { session: "s1" }, {
    readFinalState: () => "v2\n", // matches the last write: no silent edit
  });
  expect(evidence.filter((e) => e.signalKind === "silent-edit")).toHaveLength(0);
});

test("the cursor makes assembly incremental and idempotent", () => {
  const first = jsonl(userLine("first instruction"));
  const r1 = assembleEvidence(first, { session: "s1" }, { since: 0 });
  expect(r1.evidence).toHaveLength(1);
  expect(r1.consumed).toBe(1);

  // The session continues: same prefix plus a new turn.
  const second = jsonl(userLine("first instruction"), userLine("second instruction"));
  const r2 = assembleEvidence(second, { session: "s1" }, { since: r1.consumed });
  expect(r2.evidence).toHaveLength(1); // only the new turn
  expect(r2.evidence[0]!.turns).toContain("second instruction");
  expect(r2.consumed).toBe(2);
});

test("a cursor past the end (rotated transcript) restarts from zero", () => {
  const raw = jsonl(userLine("only turn"));
  const { evidence } = assembleEvidence(raw, { session: "s1" }, { since: 99 });
  expect(evidence).toHaveLength(1);
});

test("evidence ids are stable across runs, for dedup", () => {
  const raw = jsonl(userLine("stable"));
  const a = assembleEvidence(raw, { session: "s1" });
  const b = assembleEvidence(raw, { session: "s1" });
  expect(a.evidence[0]!.id).toBe(b.evidence[0]!.id);
});

test("repository falls back to the entry's cwd basename", () => {
  const raw = jsonl(userLine("scoped", { cwd: "/work/acme-api" }));
  const { evidence } = assembleEvidence(raw, { session: "s1" });
  expect(evidence[0]!.repository).toBe("acme-api");
});
