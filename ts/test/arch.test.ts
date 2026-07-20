import { expect, test } from "bun:test";
import { Glob } from "bun";
import { dirname, relative } from "node:path";

// The dependency rule from ARCHITECTURE.md section 5.3, as an executable
// fitness function. Each module may import only the modules listed here.
// A missing key means "no cross-module imports allowed" (a leaf).
const ALLOWED: Record<string, string[]> = {
  domain: [],
  store: ["domain"],
  host: ["domain", "store"],
  record: ["domain", "store"],
  retrieve: ["domain", "store"],
  infer: ["domain", "store", "retrieve", "record"],
  gate: ["domain", "store", "retrieve", "record"],
  eval: ["domain", "store", "retrieve", "record"],
  cli: ["domain", "store", "retrieve", "record"],
};

const MODULES = new Set(Object.keys(ALLOWED));
const SRC = new URL("../src/", import.meta.url).pathname;

function moduleOf(path: string): string | null {
  // path relative to src/, e.g. "domain/entry.ts" -> "domain"
  const rel = relative(SRC, path);
  const top = rel.split("/")[0];
  if (top === undefined) return null;
  // A file directly in src/ (e.g. cli.ts) is its own module by basename.
  if (!rel.includes("/")) return top.replace(/\.ts$/, "");
  return top;
}

function importedModules(source: string): string[] {
  const out: string[] = [];
  const re = /(?:import|export)[^'"]*?from\s*['"]([^'"]+)['"]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    const spec = m[1]!;
    // Only relative imports can cross internal module boundaries.
    if (!spec.startsWith(".")) continue;
    // First path segment after leaving the current dir names the target module.
    const parts = spec.replace(/^\.\//, "").split("/");
    if (spec.startsWith("../")) {
      // "../store/x" -> store ; "../cli" -> cli
      const seg = parts.filter((p) => p !== "..");
      const first = seg[0];
      if (first) out.push(first.replace(/\.ts$/, ""));
    }
    // "./x" stays inside the same module, ignore.
  }
  return out;
}

test("no source module violates the dependency rule", async () => {
  const glob = new Glob("**/*.ts");
  const violations: string[] = [];
  for await (const file of glob.scan({ cwd: SRC, absolute: true })) {
    const mod = moduleOf(file);
    if (mod === null || !MODULES.has(mod)) continue;
    const allowed = new Set(ALLOWED[mod]);
    const src = await Bun.file(file).text();
    for (const target of importedModules(src)) {
      if (target === mod) continue;
      if (!MODULES.has(target)) continue;
      if (!allowed.has(target)) {
        violations.push(`${mod} imports ${target} (${relative(SRC, file)})`);
      }
    }
  }
  expect(violations).toEqual([]);
});

test("the interception path imports nothing heavy", async () => {
  // ARCHITECTURE 5.3: the interception path is host + domain + record only,
  // and may not import infer, gate, retrieve, a parser, or a schema library.
  const forbidden = ["infer", "gate", "retrieve"];
  const guardPath = new URL("../src/host/interception.ts", import.meta.url)
    .pathname;
  const f = Bun.file(guardPath);
  if (!(await f.exists())) return; // not built yet; enforced once it exists
  const src = await f.text();
  for (const target of importedModules(src)) {
    expect(forbidden).not.toContain(target);
  }
  expect(src).not.toMatch(/from ['"](zod|valibot|arktype|@sinclair)/);
  expect(dirname(guardPath)).toContain("host");
});
