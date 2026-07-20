import { expect, test } from "bun:test";
import { Glob } from "bun";
import { dirname, relative, resolve } from "node:path";

// The dependency rule from ARCHITECTURE.md section 5.3, as an executable
// fitness function. Each module (a directory under src/) and each top-level
// entrypoint file may import only the modules listed here.
//
// Modules form the tiered core. Entrypoints (cli, injection, and later
// interception) are orchestrators: they drive the modules, so they are allowed
// to import from more of them.
const ALLOWED: Record<string, string[]> = {
  domain: [],
  store: ["domain"],
  host: ["domain", "store"],
  record: ["domain", "store"],
  retrieve: ["domain", "store"],
  infer: ["domain", "store", "retrieve", "record"],
  gate: ["domain", "store", "retrieve", "record"],
  eval: ["domain", "store", "retrieve", "record"],
  // Orchestration entrypoints.
  cli: ["domain", "store", "retrieve", "record", "gate", "infer", "host"],
  injection: ["domain", "store", "retrieve", "host"],
};

const MODULES = new Set(Object.keys(ALLOWED));
const SRC = new URL("../src/", import.meta.url).pathname;

/** The module a source file belongs to: its top directory, or its basename
 * when it sits directly in src/ (an entrypoint). */
function moduleOf(absPath: string): string {
  const rel = relative(SRC, absPath);
  if (!rel.includes("/")) return rel.replace(/\.ts$/, "");
  return rel.split("/")[0]!;
}

/** Resolve each relative import to the module it targets. */
function importedModules(absPath: string, source: string): string[] {
  const dir = dirname(absPath);
  const out: string[] = [];
  const re = /(?:import|export)[^'"]*?from\s*['"]([^'"]+)['"]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    const spec = m[1]!;
    if (!spec.startsWith(".")) continue; // only relative imports cross boundaries
    const target = moduleOf(resolve(dir, spec));
    out.push(target);
  }
  return out;
}

test("no source module violates the dependency rule", async () => {
  const glob = new Glob("**/*.ts");
  const violations: string[] = [];
  for await (const file of glob.scan({ cwd: SRC, absolute: true })) {
    const mod = moduleOf(file);
    if (!MODULES.has(mod)) continue;
    const allowed = new Set(ALLOWED[mod]);
    const src = await Bun.file(file).text();
    for (const target of importedModules(file, src)) {
      if (target === mod || !MODULES.has(target)) continue;
      if (!allowed.has(target)) {
        violations.push(`${mod} imports ${target} (${relative(SRC, file)})`);
      }
    }
  }
  expect(violations).toEqual([]);
});

test("the interception path imports nothing heavy", async () => {
  // ARCHITECTURE 5.3: the interception path is host + domain + record plus the
  // compiled projection, and may not import infer, gate, retrieve, a parser, or
  // a schema library. Enforced once the interception entrypoint exists.
  const path = new URL("../src/interception.ts", import.meta.url).pathname;
  const f = Bun.file(path);
  if (!(await f.exists())) return;
  const src = await f.text();
  for (const target of importedModules(path, src)) {
    expect(["infer", "gate", "retrieve"]).not.toContain(target);
  }
  expect(src).not.toMatch(/from ['"](zod|valibot|arktype|@sinclair)/);
});
