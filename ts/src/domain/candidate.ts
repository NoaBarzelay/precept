// A candidate: a proposed entry, before review (ARCHITECTURE.md section 6.1).
// It lives in `domain` so both `infer` (which produces it) and `record` (which
// stores it in a decision) can reference it without crossing the dependency
// rule. Committing a candidate into an Entry happens at the gate.

import type { Check } from "./check.ts";
import type {
  EnforcementTier,
  EntryKind,
  Scope,
  SignalKind,
} from "./entry.ts";

export interface Candidate {
  readonly kind: EntryKind;
  readonly scope: Scope;
  readonly content: string;
  /** The condition it holds under, stated even when "always" (R1.3, R2.3). */
  readonly condition: string;
  readonly signalKind: SignalKind;
  readonly evidenceId?: string;
  readonly quote?: string;
  /** For a rule the model proposes to enforce. */
  readonly tier?: EnforcementTier;
  readonly check?: Check;
}
