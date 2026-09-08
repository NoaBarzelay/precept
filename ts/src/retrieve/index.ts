// The derived, rebuildable retrieval index (ARCHITECTURE.md sections 5.2, 7).
//
// A SQLite FTS5 index over the cards, kept on local disk only (never synced,
// because SQLite corrupts under cloud sync). It is a projection: deletable at
// any time and rebuilt from the cards, which the rebuild-equivalence fitness
// function exercises. Long records are indexed per heading section so retrieval
// can surface the applicable part rather than the whole document (R2.7).

import { Database } from "bun:sqlite";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { Entry } from "../domain/entry.ts";
import { allEntries } from "../store/card.ts";
import { indexDbPath, vaultManifestPath } from "../store/paths.ts";
import {
  type ExternalDoc,
  readExternalNote,
  readExternalNotes,
  scanExternalNotes,
} from "../store/vault.ts";

export interface Section {
  readonly anchor: string;
  readonly text: string;
}

/** Split content into heading-delimited sections; one section if no headings. */
export function sectionize(content: string): Section[] {
  const lines = content.split("\n");
  const out: Section[] = [];
  let anchor = "";
  let buf: string[] = [];
  const flush = () => {
    const text = buf.join("\n").trim();
    if (text !== "") out.push({ anchor, text });
  };
  for (const line of lines) {
    const h = /^#{1,6}\s+(.*)$/.exec(line);
    if (h !== null) {
      flush();
      anchor = h[1]!.trim();
      buf = [line];
    } else {
      buf.push(line);
    }
  }
  flush();
  return out.length > 0 ? out : [{ anchor: "", text: content.trim() }];
}

// Common English words carry no retrieval signal and cause spurious OR matches.
const STOPWORDS = new Set<string>([
  "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
  "of", "on", "in", "at", "to", "for", "and", "or", "but", "if", "then",
  "what", "where", "when", "who", "why", "how", "which", "does", "do", "did",
  "this", "that", "these", "those", "it", "its", "with", "as", "by", "from",
  "i", "you", "we", "they", "he", "she", "can", "could", "would", "should",
  "will", "my", "your", "our", "me", "us", "so", "not", "no", "yes", "up",
]);

/**
 * Where a hit came from. `precept` is a governed entry: reviewed, kept, and
 * subject to the lifecycle. `vault` is one of Noa's own knowledge notes, indexed
 * read-only. Callers must be able to tell them apart, because presenting her own
 * writing back to her as a recorded rule would be a lie about its provenance.
 */
export type Source = "precept" | "vault";

export interface Hit {
  readonly id: string;
  readonly kind: string;
  readonly anchor: string;
  readonly text: string;
  readonly score: number;
  readonly source: Source;
}

export class Index {
  private readonly db: Database;

  constructor(path: string = indexDbPath()) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path);
    this.db.run("PRAGMA journal_mode = WAL");
    this.db.run("PRAGMA busy_timeout = 5000");
    this.db.run("PRAGMA synchronous = NORMAL");
    // The index is a rebuildable projection, so a schema change drops and
    // recreates rather than migrating: the cost is one rebuild, and carrying
    // migration code for a derived table is not worth it.
    const cols = this.db
      .query("SELECT name FROM pragma_table_info('sections')")
      .all() as { name: string }[];
    if (cols.length > 0 && !cols.some((c) => c.name === "source")) {
      this.db.run("DROP TABLE sections");
    }
    this.db.run(
      `CREATE VIRTUAL TABLE IF NOT EXISTS sections USING fts5(
         id UNINDEXED, anchor UNINDEXED, kind UNINDEXED,
         status UNINDEXED, valid_until UNINDEXED, source UNINDEXED, body,
         tokenize = 'porter unicode61'
       )`,
    );
  }

  /** Insert or replace all sections of one entry. */
  upsert(entry: Entry): void {
    this.removeById(entry.id);
    const insert = this.db.query(
      `INSERT INTO sections (id, anchor, kind, status, valid_until, source, body)
       VALUES (?, ?, ?, ?, ?, 'precept', ?)`,
    );
    const validUntil = entry.validity.validUntil ?? null;
    for (const s of sectionize(entry.content)) {
      const body = s.anchor === "" ? s.text : `${s.anchor}\n${s.text}`;
      insert.run(entry.id, s.anchor, entry.kind, entry.status, validUntil, body);
    }
  }

  /**
   * Insert or replace all sections of one of Noa's own notes. Indexed as
   * permanently live: her notes carry no validity contract, so there is nothing
   * to expire, and Precept has no standing to retire them.
   */
  upsertExternal(doc: ExternalDoc): void {
    this.removeById(doc.path);
    const insert = this.db.query(
      `INSERT INTO sections (id, anchor, kind, status, valid_until, source, body)
       VALUES (?, ?, 'knowledge', 'active', NULL, 'vault', ?)`,
    );
    for (const s of sectionize(doc.content)) {
      const anchor = s.anchor === "" ? doc.title : s.anchor;
      insert.run(doc.path, anchor, `${doc.title}\n${s.text}`);
    }
  }

  /** Remove all sections of one entry. */
  removeById(id: string): void {
    this.db.query("DELETE FROM sections WHERE id = ?").run(id);
  }

  /**
   * Drop every row and rebuild from the catalog.
   *
   * This asks the store for the entries rather than listing a directory: since
   * knowledge entries live as notes in the vault (split-by-kind placement),
   * scanning the card directory silently indexes only the conventions and
   * leaves every fact unretrievable, which is the whole point of the index.
   */
  rebuild(): void {
    // One transaction, not one per statement. A rebuild is roughly 12,000
    // inserts; committing each separately is the difference between seconds and
    // half a minute.
    const entries = allEntries();
    const docs = readExternalNotes();
    this.db.transaction(() => {
      this.db.run("DELETE FROM sections");
      for (const entry of entries) this.upsert(entry);
      for (const doc of docs) this.upsertExternal(doc);
    })();
    writeManifest(currentManifest());
  }

  /**
   * Bring the vault half of the index up to date, re-reading only what changed.
   *
   * A full rebuild takes seven seconds over 13MB, which is fine to run by hand
   * and far too slow to run on a schedule or anywhere near an interactive turn.
   * Comparing size and mtime against the manifest turns the common case, where
   * nothing or almost nothing changed, into a sub-second walk that reads no
   * bodies at all.
   *
   * The entries are left alone: they are rewritten through the store, which
   * updates the index as it goes, so only Noa's own notes drift.
   */
  refresh(): { added: number; updated: number; removed: number; unchanged: number } {
    const previous = readManifest();
    const current: Manifest = {};
    const changed: ExternalDoc[] = [];
    let added = 0;
    let updated = 0;
    let unchanged = 0;

    // Read outside the transaction: file I/O should not hold a write lock.
    for (const stat of scanExternalNotes()) {
      current[stat.path] = { mtimeMs: stat.mtimeMs, size: stat.size };
      const before = previous[stat.path];
      if (before !== undefined && before.mtimeMs === stat.mtimeMs && before.size === stat.size) {
        unchanged++;
        continue;
      }
      const doc = readExternalNote(stat.path);
      if (doc === undefined) continue;
      changed.push(doc);
      if (before === undefined) added++;
      else updated++;
    }

    // Anything the manifest knew about and the walk no longer sees is gone from
    // the vault, or has stopped being a knowledge note, so it leaves the index.
    const gone = Object.keys(previous).filter((p) => current[p] === undefined);

    this.db.transaction(() => {
      for (const doc of changed) this.upsertExternal(doc);
      for (const path of gone) this.removeById(path);
    })();

    writeManifest(current);
    return { added, updated, removed: gone.length, unchanged };
  }

  /**
   * Search the index. Returns live sections only (status active, not expired),
   * ranked best-first, bounded by the count limit and the relevance floor
   * (N9). Query text is reduced to word tokens joined with OR, so arbitrary
   * user text never trips FTS5 syntax.
   */
  search(
    query: string,
    opts: { limit?: number; floor?: number; source?: Source } = {},
  ): Hit[] {
    const limit = opts.limit ?? 8;
    const floor = opts.floor ?? 0;
    const raw = query.toLowerCase().match(/[a-z0-9_]+/g);
    if (raw === null) return [];
    // Drop stopwords so a common word like "is" cannot spuriously match.
    const tokens = raw.filter((t) => !STOPWORDS.has(t));
    if (tokens.length === 0) return [];
    const match = tokens.map((t) => `"${t}"`).join(" OR ");

    const bySource = opts.source === undefined ? "" : " AND source = ?";
    const params: (string | number)[] =
      opts.source === undefined ? [match, limit] : [match, opts.source, limit];
    const rows = this.db
      .query(
        `SELECT id, kind, anchor, source, body AS text, -bm25(sections) AS score
         FROM sections
         WHERE sections MATCH ? AND status = 'active' AND valid_until IS NULL${bySource}
         ORDER BY bm25(sections)
         LIMIT ?`,
      )
      .all(...params) as Hit[];
    return rows.filter((r) => r.score >= floor);
  }

  close(): void {
    this.db.close();
  }
}

/** The vault-note manifest: path to the size and mtime last indexed. */
type Manifest = Record<string, { mtimeMs: number; size: number }>;

function readManifest(): Manifest {
  const path = vaultManifestPath();
  if (!existsSync(path)) return {};
  try {
    return JSON.parse(readFileSync(path, "utf8")) as Manifest;
  } catch {
    return {}; // unreadable manifest costs one full re-read, not a failure
  }
}

function writeManifest(manifest: Manifest): void {
  const path = vaultManifestPath();
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(manifest));
  renameSync(tmp, path);
}

function currentManifest(): Manifest {
  const out: Manifest = {};
  for (const s of scanExternalNotes()) out[s.path] = { mtimeMs: s.mtimeMs, size: s.size };
  return out;
}
