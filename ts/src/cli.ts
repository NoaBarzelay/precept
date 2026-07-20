// The command line: inspect and operate the catalog without going through the
// agent (ARCHITECTURE.md section 6.6, R1.15, R1.16, R2.6). Commands return
// strings so they are testable; main() prints them.

import type { Candidate } from "./domain/candidate.ts";
import type { Scope } from "./domain/entry.ts";
import { review } from "./gate/gate.ts";
import { compile, writeProjection } from "./projection/projection.ts";
import { Index } from "./retrieve/index.ts";
import { retrieve } from "./retrieve/retrieve.ts";
import { allEntries, removeCard } from "./store/card.ts";

interface NoteFlags {
  scope: Scope;
  condition: string;
}

function parseNoteFlags(args: string[]): { content: string; flags: NoteFlags } {
  const positional: string[] = [];
  let scope: Scope = { kind: "global" };
  let condition = "always";
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--repo") scope = { kind: "repository", repository: args[++i] ?? "" };
    else if (a === "--lang") scope = { kind: "language", language: args[++i] ?? "" };
    else if (a === "--path") scope = { kind: "path", glob: args[++i] ?? "" };
    else if (a === "--global") scope = { kind: "global" };
    else if (a === "--condition") condition = args[++i] ?? "always";
    else positional.push(a);
  }
  return { content: positional.join(" "), flags: { scope, condition } };
}

/** Record a fact the user states directly. The CLI action is the keep. */
export function noteCmd(args: string[]): string {
  const { content, flags } = parseNoteFlags(args);
  if (content.trim() === "") return "usage: precept note <content> [--repo R | --global | --lang L | --path GLOB] [--condition C]";
  const candidate: Candidate = {
    kind: "knowledge",
    scope: flags.scope,
    content,
    condition: flags.condition,
    signalKind: "stated-knowledge",
  };
  const { entry } = review(candidate, { action: "keep" });
  return `noted ${entry!.id}`;
}

export function recallCmd(args: string[]): string {
  const query = args.join(" ");
  if (query.trim() === "") return "usage: precept recall <query>";
  const hits = retrieve(query);
  if (hits.length === 0) return "(nothing relevant)";
  return hits
    .map((h) => {
      const head = h.anchor === "" ? h.id : `${h.id} / ${h.anchor}`;
      return `${head}\n  ${h.text.replace(/\n/g, "\n  ")}`;
    })
    .join("\n");
}

export function listCmd(): string {
  const entries = allEntries();
  if (entries.length === 0) return "(catalog is empty)";
  return entries
    .map((e) => {
      const scope =
        e.scope.kind === "global"
          ? "global"
          : `${e.scope.kind}:${Object.values(e.scope).slice(1).join("")}`;
      const tier = e.tier ? ` ${e.tier}` : "";
      return `${e.id}  [${e.kind}${tier}] ${e.status} (${scope})`;
    })
    .join("\n");
}

export function removeCmd(id: string): string {
  if (id === undefined || id === "") return "usage: precept remove <id>";
  const existed = removeCard(id);
  if (!existed) return `no such entry: ${id}`;
  const index = new Index();
  try {
    index.removeById(id);
  } finally {
    index.close();
  }
  return `removed ${id}`;
}

export function reindexCmd(): string {
  const index = new Index();
  try {
    index.rebuild();
  } finally {
    index.close();
  }
  return `reindexed ${allEntries().length} entries`;
}

/** Recompile the catalog's hard rules into the projection the hot path reads. */
export function compileCmd(): string {
  const rules = compile(allEntries());
  writeProjection(rules);
  return `compiled ${rules.length} enforced rules`;
}

export function runCli(argv: string[]): string {
  const [cmd, ...rest] = argv;
  switch (cmd) {
    case "note":
      return noteCmd(rest);
    case "recall":
      return recallCmd(rest);
    case "list":
      return listCmd();
    case "remove":
      return removeCmd(rest[0] ?? "");
    case "reindex":
      return reindexCmd();
    case "compile":
      return compileCmd();
    default:
      return "commands: note, recall, list, remove, reindex, compile";
  }
}

if (import.meta.main) {
  console.log(runCli(process.argv.slice(2)));
}
