// The inference backend (ARCHITECTURE.md sections 5.2, 8). `infer` is the only
// module that reaches the network; every AI seam takes a client through this
// interface, so the whole suite runs offline against an injected fake.
//
// The real backend (a Claude subscription via the CLI, or the SDK) lands in a
// later batch behind this same interface.

import type { Candidate } from "../domain/candidate.ts";
import type { EvidenceRecord } from "../record/evidence.ts";

export interface InferenceClient {
  /**
   * Read one evidence window and propose a candidate, or abstain (null) when
   * the evidence does not identify a single clear intent (R1.2, R2.2).
   */
  propose(evidence: EvidenceRecord): Promise<Candidate | null>;
}

/** An injected, deterministic client for tests. */
export class FakeClient implements InferenceClient {
  constructor(
    private readonly script: (e: EvidenceRecord) => Candidate | null,
  ) {}

  propose(evidence: EvidenceRecord): Promise<Candidate | null> {
    return Promise.resolve(this.script(evidence));
  }
}
