// The capture step of the write path (ARCHITECTURE.md section 6.1):
// evidence -> candidate, with abstention as the default. Runs off the
// interactive turn.

import type { Candidate } from "../domain/candidate.ts";
import { appendEvidence, type EvidenceRecord } from "../record/evidence.ts";
import type { InferenceClient } from "./client.ts";

/**
 * Record the evidence, then ask the client for a candidate. Abstention (the
 * client returns null when the evidence does not resolve to one intent) records
 * nothing as a candidate and returns null (R1.2, R2.2). The evidence itself is
 * always kept, so a missed signal can be recovered by the hindsight audit
 * (R1.14).
 */
export async function capture(
  evidence: EvidenceRecord,
  client: InferenceClient,
): Promise<Candidate | null> {
  appendEvidence(evidence);
  return client.propose(evidence);
}
