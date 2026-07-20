import { expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

// The privacy boundary, enforced rather than steered (README, and the project's
// own thesis that an invariant should block, not nudge). Precept separates a
// public code plane (this repository) from a private data plane (the catalog in
// ~/.precept, the state dir, the vault). Learned content, the user's actual
// rules, style, and knowledge, must never be tracked here. gitignore states the
// intent; this test makes it a CI-gated invariant. Ported from the Python
// reference (tests/test_repo_privacy.py) when the Python was removed.

const REPO = resolve(import.meta.dir, "..", "..");

function trackedFiles(): string[] | null {
  try {
    const out = execFileSync("git", ["ls-files"], { cwd: REPO, encoding: "utf8" });
    return out.split("\n").filter((l) => l !== "");
  } catch {
    return null; // not a git checkout: skip cleanly
  }
}

// Built from fragments so this gate file does not match its own pattern source
// when it scans every tracked text file (itself included).
const PERSONAL_MARKERS = new RegExp(
  [
    "/Users/" + "[a-z]+/", // absolute home paths (machine-specific)
    "\\+1-\\d{3}-\\d{3}-\\d{4}", // US phone numbers
    "iCloud~md~" + "obsidian", // the private vault mount
  ].join("|"),
);

const TEXT_SUFFIXES = new Set([
  ".ts", ".js", ".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".cfg", ".ini",
]);

test("no personal markers in tracked text files", () => {
  const files = trackedFiles();
  if (files === null) return;
  const offenders: string[] = [];
  for (const f of files) {
    const dot = f.lastIndexOf(".");
    if (dot < 0 || !TEXT_SUFFIXES.has(f.slice(dot))) continue;
    const p = join(REPO, f);
    try {
      if (!statSync(p).isFile()) continue;
      if (PERSONAL_MARKERS.test(readFileSync(p, "utf8"))) offenders.push(f);
    } catch {
      // unreadable: skip
    }
  }
  expect(offenders).toEqual([]);
});

test("no learned catalog or local session files are tracked", () => {
  const files = trackedFiles();
  if (files === null) return;
  const offenders = files.filter((f) => {
    const name = f.split("/").pop() ?? f;
    if (f.startsWith(".claude/")) return true;
    if (name.startsWith("HANDOFF") || name.startsWith("LAUNCH-CHECKLIST")) return true;
    // The repo catalog/ may hold only a README and clearly-synthetic examples.
    if (f.startsWith("catalog/") && name !== "README.md" && !name.startsWith("example-")) {
      return true;
    }
    return false;
  });
  expect(offenders).toEqual([]);
});
