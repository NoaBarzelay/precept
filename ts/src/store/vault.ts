// Knowledge as vault notes (the split-by-kind placement decision).
//
// Precept holds two different things for two different readers. A convention is
// an instruction for the agent: Noa never opens it, and it stays a Precept card
// under the catalog root. Knowledge is for Noa: it belongs in the Obsidian vault
// as a note she can browse, wikilink, and search alongside everything else she
// has written. So knowledge serializes to her note contract, not Precept's card
// contract, and lands in the matching subject folder rather than a flat
// directory.
//
// Her contract, matched exactly against existing notes: `type: knowledge`, an
// `updated` date, title, date, topic, purpose, tags, and a trailing `## Sources`
// section. Precept's own typed fields ride in a single nested `precept:` key
// rather than being spread across the top level, so her frontmatter stays hers
// and a reader can tell at a glance which keys Precept owns. Obsidian ignores
// keys it does not know, so the note renders normally.
//
// The nested block is what makes the note round-trip: an entry written here can
// be read back as the same Entry, which is the property that keeps the vault a
// real store rather than an export target.

import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, relative } from "node:path";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { type Entry, entryError, type Scope } from "../domain/entry.ts";
import { vaultDir, vaultMapPath } from "./paths.ts";

/** The `## Sources` section, anchored to the end of the note. */
const SOURCES_BLOCK = /\n## Sources\n[\s\S]*$/;

/** A note title derived from the content: its first heading, else its first
 * sentence, trimmed to something that works as a filename. */
export function titleOf(content: string): string {
  const firstLine = content.split("\n").find((l) => l.trim() !== "") ?? "";
  const heading = /^#{1,6}\s+(.*)$/.exec(firstLine.trim());
  const raw = heading !== null ? heading[1]! : firstLine;
  const plain = raw
    .replace(/\*\*/g, "")
    .replace(/[*_`]/g, "")
    .replace(/[:/\\]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const sentence = plain.split(/(?<=[.?!])\s/)[0] ?? plain;
  const cut = sentence.length > 70 ? `${sentence.slice(0, 70).trimEnd()}` : sentence;
  return cut.replace(/[.,;]+$/, "").trim();
}

function scopeTag(scope: Scope): string {
  switch (scope.kind) {
    case "global":
      return "global";
    case "repository":
      return scope.repository;
    case "language":
      return scope.language;
    case "path":
      return scope.glob;
    case "situation":
      return scope.name;
  }
}

function slugTag(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * The Sources section. Precept-derived knowledge has no external citation: it
 * came from Noa's own session, so the honest source is the evidence it was
 * drawn from. Saying that plainly beats an empty section or a fabricated link.
 */
function sourcesSection(entry: Entry): string {
  const lines = ["## Sources"];
  const { signalKind, quote, decisionId } = entry.provenance;
  lines.push(`- Recorded by Precept from a ${signalKind} signal in Noa's own session.`);
  if (quote !== undefined && quote.trim() !== "") {
    lines.push(`- Evidence: "${quote.replace(/\s+/g, " ").trim()}"`);
  }
  if (decisionId !== undefined) lines.push(`- Decision record: ${decisionId}`);
  return lines.join("\n");
}

/** Serialize an Entry as a vault knowledge note. Throws if invalid or not
 * knowledge, since only knowledge takes this format. */
export function serializeNote(entry: Entry, today: string, title?: string): string {
  const err = entryError(entry);
  if (err !== null) throw new Error(`refusing to serialize invalid entry: ${err}`);
  if (entry.kind !== "knowledge") {
    throw new Error(`only knowledge serializes as a vault note, got '${entry.kind}'`);
  }

  const front: Record<string, unknown> = {
    type: "knowledge",
    updated: today,
    title: title ?? titleOf(entry.content),
    date: entry.validity.validFrom,
    topic: entry.validity.condition,
    purpose: "Knowledge Precept recorded from Noa's sessions and injects when relevant.",
    tags: ["precept", slugTag(scopeTag(entry.scope))].filter((t) => t !== ""),
    precept: {
      id: entry.id,
      schemaVersion: entry.schemaVersion,
      version: entry.version,
      kind: entry.kind,
      scope: entry.scope,
      status: entry.status,
      validity: entry.validity,
      provenance: entry.provenance,
      ...(entry.supersededBy !== undefined ? { supersededBy: entry.supersededBy } : {}),
    },
  };

  const body = entry.content.trim();
  return `---\n${stringifyYaml(front)}---\n\n${body}\n\n${sourcesSection(entry)}\n`;
}

/**
 * Parse a vault note back into an Entry. Throws when the note is not one
 * Precept wrote, which is the guard that keeps Precept from adopting or
 * rewriting Noa's own hand-written notes: without a `precept:` block the note
 * is hers, and Precept leaves it alone.
 */
export function parseNote(text: string): Entry {
  const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text);
  if (m === null) throw new Error("note has no frontmatter");
  const front = parseYaml(m[1]!) as Record<string, unknown>;
  const block = front.precept as Record<string, unknown> | undefined;
  if (block === undefined) {
    throw new Error("not a Precept-written note (no `precept:` frontmatter block)");
  }

  const body = (m[2] ?? "").replace(SOURCES_BLOCK, "").trim();
  const entry = { ...block, content: body } as Entry;
  const err = entryError(entry);
  if (err !== null) throw new Error(`invalid entry in note: ${err}`);
  return entry;
}

/** Whether a note carries a Precept block, without throwing. Used when scanning
 * the vault to rebuild the id-to-path map. */
export function preceptIdOf(text: string): string | null {
  try {
    return parseNote(text).id;
  } catch {
    return null;
  }
}

// --- Placement and I/O -----------------------------------------------------
//
// A note lives at <vault>/<subject folder>/<title>.md. The folder is a judgment
// call about where a fact belongs in Noa's subject tree, so it is supplied by
// the caller and never guessed here: Precept proposes placement at review time
// and Noa confirms it, which is the same always-propose-never-act-silently rule
// the rest of the loop follows. This module only validates and writes.

/** Relative folder path within the vault, e.g. "Career/Tech Industry Landscape/AI Infrastructure". */
export type Folder = string;

const BAD_FOLDER = /(^\/)|(\.\.)|(^~)/;

/** Reject a folder that escapes the vault or is not a relative subject path. */
export function folderError(folder: Folder): string | null {
  if (folder.trim() === "") return "folder is empty";
  if (BAD_FOLDER.test(folder)) return `folder '${folder}' must be a relative path inside the vault`;
  return null;
}

/** Where a note for this entry goes, given its folder and an optional explicit
 * title. Two entries whose content opens the same way derive the same title, so
 * a caller that keeps both must name at least one of them. */
export function notePath(
  vault: string,
  folder: Folder,
  entry: Entry,
  title?: string,
): string {
  return join(vault, folder, `${title ?? titleOf(entry.content)}.md`);
}

/** The id-to-path map: entry id to a vault-relative note path. */
export function readVaultMap(): Record<string, string> {
  const path = vaultMapPath();
  if (!existsSync(path)) return {};
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, string>;
}

function writeVaultMap(map: Record<string, string>): void {
  const path = vaultMapPath();
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(map, null, 1));
  renameSync(tmp, path);
}

/**
 * Write a knowledge entry as a note in the given subject folder, and record the
 * mapping. Refuses to overwrite a note Precept did not write, so a title that
 * collides with one of Noa's own files never clobbers it.
 */
export function writeNote(
  entry: Entry,
  folder: Folder,
  today: string,
  title?: string,
): string {
  const vault = vaultDir();
  if (vault === undefined) throw new Error("no vault configured (PRECEPT_VAULT unset)");
  const ferr = folderError(folder);
  if (ferr !== null) throw new Error(ferr);

  const target = notePath(vault, folder, entry, title);
  if (existsSync(target)) {
    const existing = preceptIdOf(readFileSync(target, "utf8"));
    if (existing === null) {
      throw new Error(`refusing to overwrite a note Precept did not write: ${target}`);
    }
    if (existing !== entry.id) {
      throw new Error(`title collides with a different Precept note (${existing}): ${target}`);
    }
  }

  mkdirSync(dirname(target), { recursive: true });
  const tmp = join(dirname(target), `.${entry.id}.${process.pid}.tmp`);
  writeFileSync(tmp, serializeNote(entry, today, title));
  renameSync(tmp, target);

  const map = readVaultMap();
  map[entry.id] = relative(vault, target);
  writeVaultMap(map);
  return target;
}

/** Read a vault note back as an Entry, by id. Undefined when unmapped or gone. */
export function readNote(id: string): Entry | undefined {
  const vault = vaultDir();
  if (vault === undefined) return undefined;
  const rel = readVaultMap()[id];
  if (rel === undefined) return undefined;
  const abs = join(vault, rel);
  if (!existsSync(abs)) return undefined; // moved in Obsidian: a rescan repairs it
  return parseNote(readFileSync(abs, "utf8"));
}

/** Every Precept-written note in the vault, rebuilding the id-to-path map.
 * Repairs the map after Noa moves or renames notes in Obsidian. */
export function rescanVault(): Entry[] {
  const vault = vaultDir();
  if (vault === undefined) return [];
  const out: Entry[] = [];
  const map: Record<string, string> = {};
  for (const abs of markdownFiles(vault)) {
    let text: string;
    try {
      text = readFileSync(abs, "utf8");
    } catch {
      continue;
    }
    if (!text.includes("precept:")) continue; // cheap gate before parsing
    let entry: Entry;
    try {
      entry = parseNote(text);
    } catch {
      continue; // one of Noa's own notes, or a malformed one: leave it alone
    }
    map[entry.id] = relative(vault, abs);
    out.push(entry);
  }
  writeVaultMap(map);
  return out;
}

function* markdownFiles(dir: string): Generator<string> {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    if (e.name.startsWith(".")) continue; // .git, .obsidian, .trash
    const abs = join(dir, e.name);
    if (e.isDirectory()) yield* markdownFiles(abs);
    else if (e.name.endsWith(".md")) yield abs;
  }
}

// --- Noa's own notes, read-only -------------------------------------------
//
// Precept indexes its own entries so it can inject them. That covers only what
// Precept happened to record, which is a thin slice of what Noa knows: her
// vault holds hundreds of knowledge files she compiled herself, and retrieval
// that ignores them answers "we have nothing on that" while the answer sits one
// folder away. Worse, folding a Precept note into one of her files, which is the
// right editorial move, used to delete it from retrieval.
//
// So her `type: knowledge` notes are indexed too, and strictly read-only:
// nothing here returns an Entry, so none of them can reach a write path, be
// retired, or be rewritten. They are documents to search, not entries to govern.

/** One of Noa's own knowledge notes: searchable, never writable. */
export interface ExternalDoc {
  /** Vault-relative path, which is also its stable identity. */
  readonly path: string;
  readonly title: string;
  readonly content: string;
}

/**
 * Folders excluded from the read-only index.
 *
 * `Claude` is the memory directory, already loaded into every session by
 * CLAUDE.md, so indexing it would inject the same text twice. `Claude
 * Conversations` is session transcripts: high volume, and it would feed
 * Precept's own past output back to it as though it were knowledge.
 */
const EXCLUDED_TOP_LEVEL = new Set(["Claude", "Claude Conversations"]);

/** Frontmatter `type`, read from the head of the file without parsing YAML. */
function frontmatterType(head: string): string | null {
  if (!head.startsWith("---")) return null;
  const end = head.indexOf("\n---", 3);
  const front = end === -1 ? head : head.slice(0, end);
  const m = /^type:\s*(\S+)\s*$/m.exec(front);
  return m === null ? null : m[1]!;
}

/** Frontmatter `title`, falling back to the filename. */
function frontmatterTitle(head: string, path: string): string {
  const m = /^title:\s*(.+)$/m.exec(head);
  const raw = m === null ? basename(path, ".md") : m[1]!.trim();
  return raw.replace(/^["']|["']$/g, "");
}

/**
 * Every knowledge note in the vault that Precept did not write. A note carrying
 * a `precept:` block is Precept's own and is indexed as an entry instead, so
 * including it here would double-index it.
 */
export function readExternalNotes(): ExternalDoc[] {
  const vault = vaultDir();
  if (vault === undefined) return [];
  const out: ExternalDoc[] = [];
  for (const abs of markdownFiles(vault)) {
    const rel = relative(vault, abs);
    if (EXCLUDED_TOP_LEVEL.has(rel.split("/")[0] ?? "")) continue;
    let text: string;
    try {
      text = readFileSync(abs, "utf8");
    } catch {
      continue;
    }
    const head = text.slice(0, 2000);
    if (frontmatterType(head) !== "knowledge") continue; // `note` and untagged are hers to write, not knowledge
    if (preceptIdOf(text) !== null) continue; // Precept's own, indexed as an entry
    out.push({ path: rel, title: frontmatterTitle(head, rel), content: bodyOf(text) });
  }
  return out;
}

/** The note body, without its frontmatter. */
function bodyOf(text: string): string {
  const m = /^---\n[\s\S]*?\n---\n?([\s\S]*)$/.exec(text);
  return (m === null ? text : (m[1] ?? "")).trim();
}
