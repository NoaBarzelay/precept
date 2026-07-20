// The derived, rebuildable retrieval index (ARCHITECTURE.md sections 5.2, 7).
//
// A SQLite FTS5 index over the cards, kept on local disk only (never synced,
// because SQLite corrupts under cloud sync). It is a projection: deletable at
// any time and rebuilt from the cards, which the rebuild-equivalence fitness
// function exercises. Long records are indexed per heading section so retrieval
// can surface the applicable part rather than the whole document (R2.7).

import { Database } from "bun:sqlite";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname } from "node:path";
import type { Entry } from "../domain/entry.ts";
import { readCard } from "../store/card.ts";
import { entriesDir, indexDbPath } from "../store/paths.ts";

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

export interface Hit {
  readonly id: string;
  readonly kind: string;
  readonly anchor: string;
  readonly text: string;
  readonly score: number;
}

export class Index {
  private readonly db: Database;

  constructor(path: string = indexDbPath()) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new Database(path);
    this.db.run("PRAGMA journal_mode = WAL");
    this.db.run("PRAGMA busy_timeout = 5000");
    this.db.run("PRAGMA synchronous = NORMAL");
    this.db.run(
      `CREATE VIRTUAL TABLE IF NOT EXISTS sections USING fts5(
         id UNINDEXED, anchor UNINDEXED, kind UNINDEXED,
         status UNINDEXED, valid_until UNINDEXED, body,
         tokenize = 'porter unicode61'
       )`,
    );
  }

  /** Insert or replace all sections of one entry. */
  upsert(entry: Entry): void {
    this.removeById(entry.id);
    const insert = this.db.query(
      `INSERT INTO sections (id, anchor, kind, status, valid_until, body)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
    const validUntil = entry.validity.validUntil ?? null;
    for (const s of sectionize(entry.content)) {
      const body = s.anchor === "" ? s.text : `${s.anchor}\n${s.text}`;
      insert.run(entry.id, s.anchor, entry.kind, entry.status, validUntil, body);
    }
  }

  /** Remove all sections of one entry. */
  removeById(id: string): void {
    this.db.query("DELETE FROM sections WHERE id = ?").run(id);
  }

  /** Drop every row and rebuild from the cards on disk. */
  rebuild(): void {
    this.db.run("DELETE FROM sections");
    if (!existsSync(entriesDir())) return;
    for (const file of readdirSync(entriesDir())) {
      if (!file.endsWith(".md") || file.startsWith(".")) continue;
      const id = file.slice(0, -3);
      this.upsert(readCard(id));
    }
  }

  /**
   * Search the index. Returns live sections only (status active, not expired),
   * ranked best-first, bounded by the count limit and the relevance floor
   * (N9). Query text is reduced to word tokens joined with OR, so arbitrary
   * user text never trips FTS5 syntax.
   */
  search(query: string, opts: { limit?: number; floor?: number } = {}): Hit[] {
    const limit = opts.limit ?? 8;
    const floor = opts.floor ?? 0;
    const tokens = query.match(/[A-Za-z0-9_]+/g);
    if (tokens === null || tokens.length === 0) return [];
    const match = tokens.map((t) => `"${t}"`).join(" OR ");

    const rows = this.db
      .query(
        `SELECT id, kind, anchor, body AS text, -bm25(sections) AS score
         FROM sections
         WHERE sections MATCH ? AND status = 'active' AND valid_until IS NULL
         ORDER BY bm25(sections)
         LIMIT ?`,
      )
      .all(match, limit) as Hit[];
    return rows.filter((r) => r.score >= floor);
  }

  close(): void {
    this.db.close();
  }
}
