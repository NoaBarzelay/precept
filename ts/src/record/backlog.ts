// The session-start review prompt (ARCHITECTURE.md section 5.4, R1.8).
//
// The review queue is the one part of the loop that needs a human, and nothing
// asked for it: candidates accumulated for a month unreviewed while the catalog
// stayed empty. This turns the SessionStart hook, until now a no-op, into the
// nudge: it reports what is waiting and asks the assistant to walk the backlog
// interactively rather than dumping it.
//
// Two properties keep it from becoming noise, which is the failure mode that
// gets a prompt like this ignored or removed:
//
//   Bounded. A fixed-size summary plus at most three one-line previews, so a
//   queue of three and a queue of three hundred cost the same context.
//
//   Throttled. At most one prompt per interval (default 24h), stamped to local
//   state. A backlog the user has chosen not to clear must not re-ask every
//   session. PRECEPT_BACKLOG_INTERVAL_HOURS overrides it; 0 disables the
//   throttle, which is what the tests use.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { backlogStampPath } from "../store/paths.ts";
import { listPending, type Pending } from "./queue.ts";

const PREVIEWS = 3;
const PREVIEW_CHARS = 100;
const DEFAULT_INTERVAL_HOURS = 24;

/** How long to stay quiet after prompting. 0 means never throttle. */
export function intervalHours(): number {
  const raw = process.env.PRECEPT_BACKLOG_INTERVAL_HOURS;
  if (raw === undefined) return DEFAULT_INTERVAL_HOURS;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : DEFAULT_INTERVAL_HOURS;
}

/** Whether enough time has passed since the last prompt. */
export function throttleElapsed(now: Date = new Date()): boolean {
  const hours = intervalHours();
  if (hours === 0) return true;
  const path = backlogStampPath();
  if (!existsSync(path)) return true;
  const last = Date.parse(readFileSync(path, "utf8").trim());
  if (Number.isNaN(last)) return true; // unreadable stamp: prompt rather than stay silent forever
  return now.getTime() - last >= hours * 3_600_000;
}

/** Record that the prompt fired, starting the quiet interval. */
export function stampPrompted(now: Date = new Date()): void {
  const path = backlogStampPath();
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, now.toISOString());
}

/** Count the queue by candidate kind, most numerous first. */
function byKind(pending: readonly Pending[]): string {
  const counts = new Map<string, number>();
  for (const p of pending) {
    counts.set(p.candidate.kind, (counts.get(p.candidate.kind) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([kind, n]) => `${n} ${kind}`)
    .join(", ");
}

function preview(p: Pending): string {
  const line = p.candidate.content.replace(/\s+/g, " ").trim();
  return line.length > PREVIEW_CHARS ? `${line.slice(0, PREVIEW_CHARS)}...` : line;
}

function daysSince(iso: string, now: Date): number {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return 0;
  return Math.floor((now.getTime() - then) / 86_400_000);
}

/**
 * The text to inject at session start, or "" when there is nothing to say
 * (empty queue, or the throttle has not elapsed). Pure apart from reading the
 * queue and the stamp; the caller stamps, so a caller that discards the text
 * does not start the quiet interval.
 */
export function backlogPrompt(now: Date = new Date()): string {
  const pending = listPending();
  if (pending.length === 0) return "";
  if (!throttleElapsed(now)) return "";

  const oldest = pending[0]!; // listPending sorts oldest first
  const age = daysSince(oldest.enqueuedAt, now);
  const aged = age > 0 ? `, oldest ${age} day${age === 1 ? "" : "s"} old` : "";

  const lines = [
    `Precept review queue: ${pending.length} candidate${pending.length === 1 ? "" : "s"} awaiting review (${byKind(pending)}${aged}).`,
    "Nothing enters the catalog until Noa keeps or dismisses each one.",
    "",
    "Examples:",
    ...pending.slice(0, PREVIEWS).map((p) => `- ${preview(p)}`),
    "",
    "Offer to review the backlog. If she agrees, ask about the candidates",
    "interactively in themed batches, a few at a time, each with a descriptive",
    "explanation of what it says and whether it duplicates something she already",
    "has. Do not dump the whole queue as text, and do not decide on her behalf.",
    "Commands: `precept pending`, `precept keep <id>`, `precept dismiss <id> [reason]`.",
  ];
  return lines.join("\n");
}
