// Card serialization: an Entry to and from a markdown card (ARCHITECTURE.md
// section 7). The frontmatter is the validated typed contract; the check AST
// rides in a fenced ```check block so it stays machine-parseable and
// human-inspectable; the prose body is the entry content.
//
// Every read and write validates against entryError, so a malformed card never
// enters the system and a card is never written in a shape it cannot be read
// back from.

import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  writeSync,
} from "node:fs";
import { join } from "node:path";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import type { Check } from "../domain/check.ts";
import { type Entry, entryError } from "../domain/entry.ts";
import { cardPath, entriesDir } from "./paths.ts";

const FENCE = "```";
// The check block is the final block of the card (serialize always appends it
// last), anchored to the end so a ```check fence appearing in prose content is
// left in the body rather than mistaken for the check.
const CHECK_BLOCK = /\n```check\s*\n([\s\S]*?)\n```\s*$/;

/** Serialize an Entry to card text. Throws if the entry is invalid. */
export function serialize(entry: Entry): string {
  const err = entryError(entry);
  if (err !== null) throw new Error(`refusing to serialize invalid entry: ${err}`);

  // Frontmatter carries the typed fields; the check rides in the body.
  const front: Record<string, unknown> = {
    schemaVersion: entry.schemaVersion,
    version: entry.version,
    id: entry.id,
    kind: entry.kind,
    scope: entry.scope,
    status: entry.status,
    validity: pruneUndefined(entry.validity),
    provenance: pruneUndefined(entry.provenance),
  };
  if (entry.supersededBy !== undefined) front.supersededBy = entry.supersededBy;
  if (entry.tier !== undefined) front.tier = entry.tier;
  if (entry.lifecycle !== undefined) front.lifecycle = entry.lifecycle;
  if (entry.confirmations !== undefined) front.confirmations = entry.confirmations;

  let body = entry.content.trim();
  if (entry.check !== undefined) {
    body += `\n\n${FENCE}check\n${JSON.stringify(entry.check, null, 2)}\n${FENCE}`;
  }

  return `---\n${stringifyYaml(front)}---\n\n${body}\n`;
}

/** Parse card text into an Entry. Throws on malformed or invalid content. */
export function parse(text: string): Entry {
  const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text);
  if (m === null) throw new Error("card has no frontmatter");
  const front = parseYaml(m[1]!) as Record<string, unknown>;
  let body = (m[2] ?? "").trim();

  let check: Check | undefined;
  const cm = CHECK_BLOCK.exec(body);
  if (cm !== null) {
    check = JSON.parse(cm[1]!) as Check;
    body = body.replace(CHECK_BLOCK, "").trim();
  }

  const entry: Entry = {
    schemaVersion: front.schemaVersion as number,
    version: front.version as number,
    id: front.id as string,
    kind: front.kind as Entry["kind"],
    scope: front.scope as Entry["scope"],
    content: body,
    validity: front.validity as Entry["validity"],
    provenance: front.provenance as Entry["provenance"],
    status: front.status as Entry["status"],
    ...(front.supersededBy !== undefined
      ? { supersededBy: front.supersededBy as string }
      : {}),
    ...(front.tier !== undefined ? { tier: front.tier as Entry["tier"] } : {}),
    ...(check !== undefined ? { check } : {}),
    ...(front.lifecycle !== undefined
      ? { lifecycle: front.lifecycle as Entry["lifecycle"] }
      : {}),
    ...(front.confirmations !== undefined
      ? { confirmations: front.confirmations as number }
      : {}),
  };

  const err = entryError(entry);
  if (err !== null) throw new Error(`invalid card: ${err}`);
  return entry;
}

/**
 * Write an entry as a card, atomically and crash-safely: write a temp file in
 * the same directory, fsync it, rename over the target, then fsync the
 * directory so a concurrent reader sees the old file or the new one, never a
 * partial one. (On macOS full durability also wants F_FULLFSYNC, which the
 * stdlib does not expose; DECISIONS.md records the full recipe.)
 */
export function writeCard(entry: Entry): string {
  const dir = entriesDir();
  mkdirSync(dir, { recursive: true });
  const target = cardPath(entry.id);
  const text = serialize(entry);

  const tmp = join(dir, `.${entry.id}.${process.pid}.tmp`);
  const fd = openSync(tmp, "w");
  try {
    writeSync(fd, text);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(tmp, target);
  fsyncDir(dir);
  return target;
}

/** Read and validate a card by id. Throws if missing or invalid. */
export function readCard(id: string): Entry {
  return parse(readFileSync(cardPath(id), "utf8"));
}

/** All entry ids on disk, sorted. */
export function listEntryIds(): string[] {
  const dir = entriesDir();
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".md") && !f.startsWith("."))
    .map((f) => f.slice(0, -3))
    .sort();
}

/** All entries on disk. */
export function allEntries(): Entry[] {
  return listEntryIds().map(readCard);
}

/** Hard-delete a card (R1.16 removal). Returns true if it existed. */
export function removeCard(id: string): boolean {
  const path = cardPath(id);
  if (!existsSync(path)) return false;
  rmSync(path);
  return true;
}

function fsyncDir(dir: string): void {
  const dfd = openSync(dir, "r");
  try {
    fsyncSync(dfd);
  } catch {
    // Some platforms reject fsync on a directory fd; the rename is already
    // durable enough for a single-user tool.
  } finally {
    closeSync(dfd);
  }
}

function pruneUndefined<T extends object>(obj: T): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) out[k as keyof T] = v as T[keyof T];
  }
  return out;
}
