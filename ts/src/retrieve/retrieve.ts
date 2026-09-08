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

/**
 * The N9 injection bounds, from the README ("2,000 characters, top 5 entries").
 * The relevance floor is a calibration knob left at 0 until a Recall@5 baseline
 * sets it, consistent with the thresholds the spec leaves unset by design.
 */
export const INJECTION_BOUNDS = { limit: 5, floor: 0, maxChars: 2000 } as const;

/**
 * Slots each source is guaranteed, if it has any hits at all.
 *
 * The two sources are wildly unequal in size: on this machine roughly 95
 * governed entries against 584 vault notes, some of them 200KB. That asymmetry
 * makes pure score ranking risky, because the vault can crowd the governed
 * entries out of every slot on a broad query.
 *
 * The fix is a foothold, not a priority order. An earlier version ranked
 * governed entries first unconditionally, and it was measurably worse than
 * doing nothing: for "discrete-time hazard models, censored observation
 * stopped", the correct section scored 33.5 in the vault while the best
 * governed entry scored 6.0, and the reservation still put three entries
 * scoring 6.0, 5.3 and 4.7 ahead of it. One of them was 1,084 characters, so
 * the character budget then truncated away the answer. Relevance has to
 * dominate once the gap is that wide.
 *
 * So each source is guaranteed its own best hit, every remaining slot goes to
 * whatever scores highest across both, and the result is ordered by score so
 * the character budget truncates the weakest hit rather than the best one.
 */
export const GUARANTEED_SLOTS = 1;

/** Search the default index for the query, applying the N9 injection budget. */
export function retrieve(query: string, opts: RetrieveOptions = {}): Hit[] {
  const bounded = { ...INJECTION_BOUNDS, ...opts };
  const index = new Index();
  try {
    return budget(merge(index, query, bounded), bounded);
  } finally {
    index.close();
  }
}

/** Combine the two sources under the foothold rule described above. */
function merge(index: Index, query: string, bounded: Required<RetrieveOptions>): Hit[] {
  const { limit } = bounded;
  const governed = index.search(query, { ...bounded, limit, source: "precept" });
  const vault = index.search(query, { ...bounded, limit, source: "vault" });

  const out: Hit[] = [];
  const seen = new Set<Hit>();
  const take = (h: Hit | undefined): void => {
    if (h === undefined || seen.has(h) || out.length >= limit) return;
    seen.add(h);
    out.push(h);
  };

  for (let i = 0; i < GUARANTEED_SLOTS; i++) {
    take(governed[i]);
    take(vault[i]);
  }
  for (const h of [...governed, ...vault].sort((a, b) => b.score - a.score)) take(h);
  return out.sort((a, b) => b.score - a.score);
}

/** Apply the total-size cap over already count- and floor-bounded hits. The cap
 * is hard: the last hit is truncated to fit rather than allowed to overshoot,
 * so one large section cannot blow the bound (N9). */
export function budget(hits: Hit[], opts: RetrieveOptions = {}): Hit[] {
  const maxChars = opts.maxChars ?? INJECTION_BOUNDS.maxChars;
  const out: Hit[] = [];
  let used = 0;
  for (const h of hits) {
    if (used >= maxChars) break;
    const remaining = maxChars - used;
    if (h.text.length <= remaining) {
      out.push(h);
      used += h.text.length;
    } else {
      out.push({ ...h, text: `${h.text.slice(0, Math.max(0, remaining - 3))}...` });
      break;
    }
  }
  return out;
}

/**
 * Render hits as an additionalContext block for injection.
 *
 * The two sources are labelled differently on purpose. A governed entry is
 * something Noa reviewed and kept, so it carries authority. A vault hit is her
 * own writing, retrieved as reference; presenting it back to her as a recorded
 * rule would misstate where it came from and what standing it has.
 */
export function assembleContext(hits: Hit[]): string {
  if (hits.length === 0) return "";
  const parts = hits.map((h) => {
    if (h.source === "vault") {
      const where = h.anchor === "" ? h.id : `${h.id} / ${h.anchor}`;
      return `- [Noa's own note: ${where}] ${h.text}`;
    }
    const head = h.anchor === "" ? h.id : `${h.id} / ${h.anchor}`;
    return `- (${head}) ${h.text}`;
  });
  return `Relevant recorded knowledge:\n${parts.join("\n")}`;
}
