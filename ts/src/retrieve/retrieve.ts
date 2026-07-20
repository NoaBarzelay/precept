// Assemble the injected slice (ARCHITECTURE.md sections 6.3, 7). This is the
// one place the injection budget is applied: a count cap and a relevance floor
// on the index search, plus a total-size cap here, so what Precept injects does
// not grow with the catalog (N9).

import { type Hit, Index } from "./index.ts";

export interface RetrieveOptions {
  /** Max sections to inject. */
  limit?: number;
  /** Minimum relevance score to inject. */
  floor?: number;
  /** Max total characters of the assembled block. */
  maxChars?: number;
}

const DEFAULTS = { limit: 8, floor: 0, maxChars: 4000 } as const;

/** Search the default index for the query, applying the injection budget. */
export function retrieve(query: string, opts: RetrieveOptions = {}): Hit[] {
  const index = new Index();
  try {
    return budget(index.search(query, opts), opts);
  } finally {
    index.close();
  }
}

/** Apply the total-size cap over already count- and floor-bounded hits. */
export function budget(hits: Hit[], opts: RetrieveOptions = {}): Hit[] {
  const maxChars = opts.maxChars ?? DEFAULTS.maxChars;
  const out: Hit[] = [];
  let used = 0;
  for (const h of hits) {
    used += h.text.length;
    if (used > maxChars && out.length > 0) break;
    out.push(h);
  }
  return out;
}

/** Render hits as an additionalContext block for injection. */
export function assembleContext(hits: Hit[]): string {
  if (hits.length === 0) return "";
  const parts = hits.map((h) => {
    const head = h.anchor === "" ? h.id : `${h.id} / ${h.anchor}`;
    return `- (${head}) ${h.text}`;
  });
  return `Relevant recorded knowledge:\n${parts.join("\n")}`;
}
