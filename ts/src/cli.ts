// The command line: inspect and operate the catalog without going through the
// agent (ARCHITECTURE.md section 6.6, R1.15, R1.16, R2.6). Commands return
// strings so they are testable; main() prints them.

import type { Candidate } from "./domain/candidate.ts";
import { conflictsAmong } from "./domain/currency.ts";
import {
  confirmOnce,
  type Entry,
  narrowOnReject,
  retire,
  type Scope,
  supersede,
} from "./domain/entry.ts";
import { firing } from "./domain/validate.ts";
import { install, registeredEvents, uninstall } from "./host/install.ts";
import { ingestTranscriptFile } from "./host/transcript.ts";
import { review } from "./gate/gate.ts";
import { makeClient } from "./infer/cli_client.ts";
import { detect } from "./infer/detect.ts";
import { compile, writeProjection } from "./projection/projection.ts";
import { appendEvidence, readEvidence } from "./record/evidence.ts";
import { readHistory } from "./record/history.ts";
import { getPending, listPending, removePending } from "./record/queue.ts";
import { Index } from "./retrieve/index.ts";
import { retrieve } from "./retrieve/retrieve.ts";
import { allEntries, readCard, removeCard, writeCard } from "./store/card.ts";
import { withCardLock } from "./store/lock.ts";

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

function recompile(): void {
  writeProjection(compile(allEntries()));
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Drop one entry from the search index (a governed entry leaves retrieval). */
function dropFromIndex(id: string): void {
  const index = new Index();
  try {
    index.removeById(id);
  } finally {
    index.close();
  }
}

/**
 * Reconcile the derived state after a currency transition: a retired or
 * superseded entry must leave both the compiled projection (or a dead hard rule
 * keeps enforcing) and the search index (or it keeps being retrieved).
 */
function reconcileAfterGovern(id: string): void {
  recompile();
  dropFromIndex(id);
}

/** Live entries that lexically and structurally conflict with a candidate (R1.4). */
function conflictsFor(candidate: Candidate): Entry[] {
  const ids = [...new Set(retrieve(candidate.content).map((h) => h.id))];
  const entries: Entry[] = [];
  for (const id of ids) {
    try {
      entries.push(readCard(id));
    } catch {
      // a hit whose card was removed since indexing: skip
    }
  }
  return conflictsAmong(candidate, entries);
}

/** Retire an entry: invalidate-not-delete, and drop it from the hot path (R1.9). */
export function retireCmd(id: string): string {
  if (id === undefined || id === "") return "usage: precept retire <id>";
  let card;
  try {
    card = readCard(id);
  } catch {
    return `no such entry: ${id}`;
  }
  if (card.status !== "active") return `${id} is already ${card.status}`;
  withCardLock(id, () => writeCard(retire(readCard(id), today())));
  reconcileAfterGovern(id);
  return `retired ${id}`;
}

/** Supersede an entry with the one that replaces it (R1.10, R2.9). */
export function supersedeCmd(args: string[]): string {
  const [oldId, newId] = args;
  if (oldId === undefined || oldId === "" || newId === undefined || newId === "") {
    return "usage: precept supersede <old-id> <new-id>";
  }
  let older;
  try {
    older = readCard(oldId);
  } catch {
    return `no such entry: ${oldId}`;
  }
  try {
    readCard(newId);
  } catch {
    return `no such successor: ${newId}`;
  }
  if (older.status !== "active") return `${oldId} is already ${older.status}`;
  withCardLock(oldId, () => writeCard(supersede(readCard(oldId), newId, today())));
  reconcileAfterGovern(oldId);
  return `superseded ${oldId} by ${newId}`;
}

/** Confirm a probationary rule's enforcement was intended (R1.21). */
export function confirmCmd(id: string): string {
  if (id === undefined || id === "") return "usage: precept confirm <id>";
  let result: string;
  try {
    const next = withCardLock(id, () => {
      const current = readCard(id);
      const advanced = confirmOnce(current);
      if (advanced === current) {
        result = current.lifecycle === "operational"
          ? `${id} is already operational`
          : `${id} is not a probationary rule`;
        return current;
      }
      writeCard(advanced);
      result =
        advanced.lifecycle === "operational"
          ? `${id} graduated to operational after ${advanced.confirmations} confirmations`
          : `${id} confirmed (${advanced.confirmations}/3)`;
      return advanced;
    });
    if (next.lifecycle === "operational") recompile();
    return result!;
  } catch (e) {
    return `cannot confirm ${id}: ${e instanceof Error ? e.message : String(e)}`;
  }
}

/** List the candidates the detector has proposed and are awaiting review. */
export function pendingCmd(): string {
  const pending = listPending();
  if (pending.length === 0) return "(nothing pending review)";
  return pending
    .map((p) => {
      const c = p.candidate;
      const tier = c.tier === "hard" ? " [would enforce]" : "";
      const conflicts = conflictsFor(c);
      const warn =
        conflicts.length > 0
          ? `\n  may duplicate: ${conflicts.map((e) => e.id).join(", ")} (review to reconcile)`
          : "";
      return `${p.id}  (${c.kind}, ${c.signalKind})${tier}\n  ${c.content}${warn}`;
    })
    .join("\n");
}

/** Keep a pending candidate: commit it through the review gate. */
export function keepCmd(id: string): string {
  if (id === undefined || id === "") return "usage: precept keep <id>";
  const p = getPending(id);
  if (p === undefined) return `no pending candidate ${id}`;
  // Surface an existing near-duplicate so the reviewer can supersede it (R1.4).
  const conflicts = conflictsFor(p.candidate);
  const { entry } = review(p.candidate, { action: "keep" });
  removePending(id);
  const note =
    conflicts.length > 0
      ? `; may duplicate ${conflicts.map((e) => e.id).join(", ")} (precept supersede <id> ${entry!.id})`
      : "";
  return `kept ${entry!.id} (${entry!.tier ?? entry!.kind})${note}`;
}

/** Dismiss a pending candidate: record the decision, commit nothing. */
export function dismissCmd(args: string[]): string {
  const [id, ...rest] = args;
  if (id === undefined || id === "") return "usage: precept dismiss <id> [reason]";
  const p = getPending(id);
  if (p === undefined) return `no pending candidate ${id}`;
  review(p.candidate, { action: "dismiss", reason: rest.join(" ") || "dismissed at review" });
  removePending(id);
  return `dismissed ${id}`;
}

/** Register Precept's hooks in Claude Code's settings.json (N8). */
export function installCmd(): string {
  const path = install();
  return `installed Precept hooks (${registeredEvents().join(", ")}) into ${path}`;
}

/** Remove exactly Precept's hooks from settings.json (the exact inverse, N8). */
export function uninstallCmd(): string {
  const path = uninstall();
  return `removed Precept hooks from ${path}`;
}

/**
 * Read a finished session transcript and record the evidence it yields (the
 * manual counterpart to the SessionEnd observation trigger). Dedups by
 * content-derived evidence id, so re-running it is idempotent.
 */
export function ingestCmd(args: string[]): string {
  const positional: string[] = [];
  let session: string | undefined;
  let repository: string | undefined;
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--session") session = args[++i];
    else if (a === "--repo") repository = args[++i];
    else positional.push(a);
  }
  const path = positional[0];
  if (path === undefined || path === "") {
    return "usage: precept ingest <transcript.jsonl> [--session S] [--repo R]";
  }
  const sess = session ?? path;
  const evidence = ingestTranscriptFile(path, {
    session: sess,
    ...(repository !== undefined ? { repository } : {}),
  });
  const seen = new Set(readEvidence().map((e) => e.id));
  let appended = 0;
  for (const record of evidence) {
    if (seen.has(record.id)) continue;
    appendEvidence(record);
    seen.add(record.id);
    appended++;
  }
  return appended === 0
    ? "ingested transcript; no new evidence (nothing new, or unreadable)"
    : `ingested transcript; recorded ${appended} evidence record(s)`;
}

/** Run detection over recorded evidence with the configured backend. Async
 * because it consults the model; not routed through the sync dispatcher. */
export async function detectCmd(): Promise<string> {
  const evidence = readEvidence();
  if (evidence.length === 0) return "(no recorded evidence to review)";
  const { queued, proposed, filtered } = await detect(evidence, makeClient());
  const gated = `${filtered} filtered before the model, ${proposed} sent`;
  return queued === 0
    ? `detection ran; nothing proposed (${gated}; no backend configured, or all abstained)`
    : `detection queued ${queued} candidate(s) for review (${gated})`;
}

/** Show how often a rule would have fired over recorded history (the review
 * surface: judge a rule by real cases, not a rationale). */
export function firingCmd(id: string): string {
  if (id === undefined || id === "") return "usage: precept firing <id>";
  let card;
  try {
    card = readCard(id);
  } catch {
    return `no such entry: ${id}`;
  }
  if (card.check === undefined) return `${id} is not an enforcing rule`;
  const f = firing(card.check, readHistory().map((h) => h.facts));
  if (f.count === 0) return `${id} would not have fired on any recorded call`;
  const examples = f.examples
    .map((e) => `  - ${JSON.stringify(e.toolInput)}`)
    .join("\n");
  return `${id} would have fired on ${f.count} recorded call(s):\n${examples}`;
}

/** Reject a probationary rule: narrow its condition and reset (R1.20). */
export function rejectCmd(args: string[]): string {
  const [id, ...rest] = args;
  if (id === undefined || id === "") return "usage: precept reject <id> [--condition C]";
  let condition: string | undefined;
  for (let i = 0; i < rest.length; i++) {
    if (rest[i] === "--condition") condition = rest[++i];
  }
  try {
    withCardLock(id, () => {
      const current = readCard(id);
      const narrowed = narrowOnReject(current, condition);
      if (narrowed === current) throw new Error("not a hard rule");
      writeCard(narrowed);
    });
    recompile();
    return condition !== undefined
      ? `${id} narrowed to "${condition}" and reset`
      : `${id} reset`;
  } catch (e) {
    return `cannot reject ${id}: ${e instanceof Error ? e.message : String(e)}`;
  }
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
    case "confirm":
      return confirmCmd(rest[0] ?? "");
    case "reject":
      return rejectCmd(rest);
    case "retire":
      return retireCmd(rest[0] ?? "");
    case "supersede":
      return supersedeCmd(rest);
    case "firing":
      return firingCmd(rest[0] ?? "");
    case "install":
      return installCmd();
    case "uninstall":
      return uninstallCmd();
    case "ingest":
      return ingestCmd(rest);
    case "pending":
      return pendingCmd();
    case "keep":
      return keepCmd(rest[0] ?? "");
    case "dismiss":
      return dismissCmd(rest);
    default:
      return "commands: install, uninstall, note, recall, list, remove, reindex, compile, confirm, reject, retire, supersede, firing, ingest, detect, pending, keep, dismiss";
  }
}

if (import.meta.main) {
  const argv = process.argv.slice(2);
  const output = argv[0] === "detect" ? await detectCmd() : runCli(argv);
  console.log(output);
}
