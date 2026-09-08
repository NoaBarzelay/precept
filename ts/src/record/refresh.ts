// The vault-refresh throttle (ARCHITECTURE.md section 5.4).
//
// Noa's own knowledge notes are indexed read-only, so the index drifts whenever
// she writes in Obsidian, which produces no evidence and no tool calls. Nothing
// in the loop would notice. A periodic refresh closes that, and this module owns
// the one piece of operational state it needs: when it last ran.
//
// It lives in `record` rather than beside the refresh itself because the
// observation entrypoint drives it and may not reach into `store` or `retrieve`
// directly; `record` is where operational state belongs, the same way the
// session-start backlog stamp does.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { refreshStampPath } from "../store/paths.ts";

/** How long the vault index may go stale. 0 refreshes every session end. */
const DEFAULT_INTERVAL_MINUTES = 30;

function intervalMs(): number {
  const raw = process.env.PRECEPT_REFRESH_INTERVAL_MINUTES;
  if (raw === undefined) return DEFAULT_INTERVAL_MINUTES * 60_000;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n * 60_000 : DEFAULT_INTERVAL_MINUTES * 60_000;
}

/**
 * Whether to refresh the vault index now.
 *
 * Unlike detection this is not gated on the inference backend, because it
 * spends no tokens: it reads files. The throttle exists only so a run of short
 * sessions does not spawn a process every few minutes. It is deliberately not
 * gated on new evidence either, since Noa editing her own notes is exactly the
 * change that must be picked up and it generates no evidence at all.
 */
export function shouldRefreshIndex(now: Date = new Date()): boolean {
  if (process.env.PRECEPT_INFERENCE_SUBPROCESS === "1") return false;
  const interval = intervalMs();
  if (interval === 0) return true;
  const path = refreshStampPath();
  if (!existsSync(path)) return true;
  const last = Date.parse(readFileSync(path, "utf8").trim());
  if (Number.isNaN(last)) return true; // unreadable stamp: refresh rather than stall forever
  return now.getTime() - last >= interval;
}

/** Record that a refresh was started, beginning the quiet interval. */
export function stampRefreshed(now: Date = new Date()): void {
  const path = refreshStampPath();
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, now.toISOString());
}
