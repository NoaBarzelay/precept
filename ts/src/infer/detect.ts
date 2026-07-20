// Detection: turn recorded evidence into candidates awaiting review
// (ARCHITECTURE.md section 6.1). This is the live producer of the learning
// loop. It runs off the interactive turn, proposes a candidate per evidence
// window through the injected client, and enqueues the ones that are not
// abstentions (R1.2, R2.2). The client is the only model seam, so the whole
// loop runs offline against a fake.

import type { EvidenceRecord } from "../record/evidence.ts";
import { enqueue } from "../record/queue.ts";
import type { InferenceClient } from "./client.ts";

/**
 * Propose a candidate for each evidence record and enqueue the non-abstentions.
 * Returns the number queued for review.
 */
export async function detect(
  evidence: readonly EvidenceRecord[],
  client: InferenceClient,
): Promise<number> {
  let queued = 0;
  for (const record of evidence) {
    const candidate = await client.propose(record);
    if (candidate === null) continue; // abstain: nothing enters review
    enqueue(candidate);
    queued++;
  }
  return queued;
}
