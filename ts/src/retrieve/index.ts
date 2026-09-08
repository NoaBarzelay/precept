// The derived, rebuildable retrieval index (ARCHITECTURE.md sections 5.2, 7).
//
// A SQLite FTS5 index over the cards, kept on local disk only (never synced,
// because SQLite corrupts under cloud sync). It is a projection: deletable at
// any time and rebuilt from the cards, which the rebuild-equivalence fitness
// function exercises. Long records are indexed per heading section so retrieval
// can surface the applicable part rather than the whole document (R2.7).

import { Database } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import type { Entry } from "../domain/entry.ts";
import { allEntries } from "../store/card.ts";
import { indexDbPath } from "../store/paths.ts";
import { type ExternalDoc, readExternalNotes } from "../store/vault.ts";

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
    this.db.run("DELETE FROM sections");
    for (const entry of allEntries()) this.upsert(entry);
    for (const doc of readExternalNotes()) this.upsertExternal(doc);
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
