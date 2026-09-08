// Detection: turn recorded evidence into candidates awaiting review
// (ARCHITECTURE.md section 6.1). This is the live producer of the learning
// loop. It runs off the interactive turn, proposes a candidate per evidence
// window through the injected client, and enqueues the ones that are not
// abstentions (R1.2, R2.2). The client is the only model seam, so the whole
// loop runs offline against a fake.
//
// Two gates stand before the model, both there to bound spend (Risk 5). The
// proposal ledger skips a window already sent on an earlier run: the evidence
// log is append-only and read whole every time, so without it each run re-pays
// for the entire history and the queue fills with duplicates of one window.
// The cheap pre-filter then skips evidence that does not plausibly carry a
// durable item. Skipped evidence stays in the append-only log for the R1.14
// hindsight pass; the gates only decide what to pay for now.

import type { EvidenceRecord } from "../record/evidence.ts";
import { appendProposed, readProposed } from "../record/proposed.ts";
import { enqueue } from "../record/queue.ts";
import type { InferenceClient } from "./client.ts";
import { worthProposing } from "./prefilter.ts";

export interface DetectResult {
  /** Candidates enqueued for review (non-abstentions the model proposed). */
  readonly queued: number;
  /** Evidence records sent to the model (passed both gates). */
  readonly proposed: number;
  /** Evidence records the cost gate skipped before any model call. */
  readonly filtered: number;
  /** Evidence records an earlier run already sent to the model. */
  readonly alreadyProposed: number;
}

/**
 * Propose a candidate for each evidence record that passes the gates and
 * enqueue the non-abstentions. Returns how many were queued, sent to the model,
 * filtered before it, and skipped as already sent.
 *
 * The ledger is appended before the call, not after, so a crash or a killed
 * background process cannot leave a window that was paid for looking unpaid.
 */
export async function detect(
  evidence: readonly EvidenceRecord[],
  client: InferenceClient,
): Promise<DetectResult> {
  const seen = readProposed();
  let queued = 0;
  let proposed = 0;
  let filtered = 0;
  let alreadyProposed = 0;
  for (const record of evidence) {
    if (seen.has(record.id)) {
      alreadyProposed++; // paid for on an earlier run
      continue;
    }
    if (!worthProposing(record)) {
      filtered++; // retained in the log, just not paid for now
      continue;
    }
    appendProposed(record.id);
    seen.add(record.id); // a duplicate id within one run pays once
    proposed++;
    const candidate = await client.propose(record);
    if (candidate === null) continue; // abstain: nothing enters review
    enqueue(candidate);
    queued++;
  }
  return { queued, proposed, filtered, alreadyProposed };
}
