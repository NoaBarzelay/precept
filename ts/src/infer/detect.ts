// Detection: turn recorded evidence into candidates awaiting review
// (ARCHITECTURE.md section 6.1). This is the live producer of the learning
// loop. It runs off the interactive turn, proposes a candidate per evidence
// window through the injected client, and enqueues the ones that are not
// abstentions (R1.2, R2.2). The client is the only model seam, so the whole
// loop runs offline against a fake.
//
// A cheap pre-filter gates the model call (Risk 5): evidence that does not
// plausibly carry a durable item is skipped before spending a call. Skipped
// evidence stays in the append-only log for the R1.14 hindsight pass; the gate
// only decides what to pay for now.

import type { EvidenceRecord } from "../record/evidence.ts";
import { enqueue } from "../record/queue.ts";
import type { InferenceClient } from "./client.ts";
import { worthProposing } from "./prefilter.ts";

export interface DetectResult {
  /** Candidates enqueued for review (non-abstentions the model proposed). */
  readonly queued: number;
  /** Evidence records sent to the model (passed the cost gate). */
  readonly proposed: number;
  /** Evidence records the cost gate skipped before any model call. */
  readonly filtered: number;
}

/**
 * Propose a candidate for each evidence record that passes the cost gate and
 * enqueue the non-abstentions. Returns how many were queued, sent to the model,
 * and filtered before it.
 */
export async function detect(
  evidence: readonly EvidenceRecord[],
  client: InferenceClient,
): Promise<DetectResult> {
  let queued = 0;
  let proposed = 0;
  let filtered = 0;
  for (const record of evidence) {
    if (!worthProposing(record)) {
      filtered++; // retained in the log, just not paid for now
      continue;
    }
    proposed++;
    const candidate = await client.propose(record);
    if (candidate === null) continue; // abstain: nothing enters review
    enqueue(candidate);
    queued++;
  }
  return { queued, proposed, filtered };
}
