import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  applyInstall,
  MANAGED_MARKER,
  registeredEvents,
  stripManaged,
} from "../../src/host/install.ts";
import { installCmd, uninstallCmd } from "../../src/cli.ts";

const RUNTIME = "/opt/bun/bin/bun";
const SRC = "/work/precept/ts/src";

test("install registers a hook for every entrypoint event", () => {
  const out = applyInstall({}, RUNTIME, SRC) as { hooks: Record<string, unknown[]> };
  for (const event of registeredEvents()) {
    expect(out.hooks[event]).toBeDefined();
    expect(out.hooks[event]!.length).toBeGreaterThan(0);
  }
  // PreToolUse guards every tool via the "*" matcher.
  const pre = out.hooks.PreToolUse![0] as { matcher?: string; hooks: { command: string }[] };
  expect(pre.matcher).toBe("*");
  expect(pre.hooks[0]!.command).toContain("interception.ts");
  expect(pre.hooks[0]!.command).toContain(RUNTIME);
  expect(pre.hooks[0]!.command).toContain(MANAGED_MARKER);
});

test("install is idempotent: re-running does not accumulate duplicates", () => {
  const once = applyInstall({}, RUNTIME, SRC);
  const twice = applyInstall(once, RUNTIME, SRC);
  expect(JSON.stringify(twice)).toBe(JSON.stringify(once));
});

test("install preserves the user's own hooks and settings", () => {
  const user = {
    model: "opus",
    hooks: {
      PreToolUse: [
        { matcher: "Bash", hooks: [{ type: "command", command: "my-linter" }] },
      ],
      Notification: [{ hooks: [{ type: "command", command: "notify-send" }] }],
    },
  };
  const out = applyInstall(user, RUNTIME, SRC) as {
    model: string;
    hooks: Record<string, { hooks: { command: string }[] }[]>;
  };
  expect(out.model).toBe("opus"); // untouched top-level setting
  // The user's PreToolUse hook survives alongside Precept's.
  const commands = out.hooks.PreToolUse!.flatMap((e) => e.hooks.map((h) => h.command));
  expect(commands).toContain("my-linter");
  expect(commands.some((c) => c.includes("interception.ts"))).toBe(true);
  // A user event Precept does not touch is preserved verbatim.
  expect(out.hooks.Notification![0]!.hooks[0]!.command).toBe("notify-send");
});

test("uninstall is the exact inverse of install", () => {
  const user = {
    model: "opus",
    hooks: {
      PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "my-linter" }] }],
    },
  };
  const installed = applyInstall(user, RUNTIME, SRC);
  const removed = stripManaged(installed);
  expect(JSON.stringify(removed)).toBe(JSON.stringify(user));
});

test("uninstall on settings with no Precept hooks is a no-op", () => {
  const user = { hooks: { PreToolUse: [{ hooks: [{ type: "command", command: "x" }] }] } };
  expect(JSON.stringify(stripManaged(user))).toBe(JSON.stringify(user));
});

test("uninstall drops the hooks key entirely when only Precept's were present", () => {
  const installed = applyInstall({}, RUNTIME, SRC);
  const removed = stripManaged(installed) as Record<string, unknown>;
  expect(removed.hooks).toBeUndefined();
});

// End-to-end through the CLI against a temp Claude home (never the real one).
let claudeHome: string;

beforeEach(() => {
  claudeHome = mkdtempSync(join(tmpdir(), "precept-claude-"));
  process.env.PRECEPT_CLAUDE_HOME = claudeHome;
});

afterEach(() => {
  delete process.env.PRECEPT_CLAUDE_HOME;
  rmSync(claudeHome, { recursive: true, force: true });
});

test("the CLI writes, backs up, and exactly reverts settings.json", () => {
  const path = join(claudeHome, "settings.json");
  writeFileSync(path, JSON.stringify({ model: "opus" }, null, 2));

  expect(installCmd()).toContain("installed Precept hooks");
  const afterInstall = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
  expect(afterInstall.hooks).toBeDefined();
  expect(afterInstall.model).toBe("opus");
  expect(existsSync(`${path}.bak`)).toBe(true); // prior file kept

  expect(uninstallCmd()).toContain("removed Precept hooks");
  const afterUninstall = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
  expect(afterUninstall.hooks).toBeUndefined();
  expect(afterUninstall.model).toBe("opus");
});

test("install into a fresh Claude home with no settings file creates one", () => {
  expect(installCmd()).toContain("installed Precept hooks");
  const path = join(claudeHome, "settings.json");
  expect(existsSync(path)).toBe(true);
  const s = JSON.parse(readFileSync(path, "utf8")) as { hooks: Record<string, unknown> };
  expect(Object.keys(s.hooks).length).toBeGreaterThan(0);
});
