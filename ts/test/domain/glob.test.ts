import { expect, test } from "bun:test";
import { globMatch } from "../../src/domain/glob.ts";

test("star matches within a segment, not across", () => {
  expect(globMatch("*.ts", "index.ts")).toBe(true);
  expect(globMatch("*.ts", "src/index.ts")).toBe(false);
  expect(globMatch("src/*.ts", "src/index.ts")).toBe(true);
  expect(globMatch("src/*.ts", "src/sub/index.ts")).toBe(false);
});

test("doublestar matches across segments", () => {
  expect(globMatch("src/**/*.ts", "src/index.ts")).toBe(true);
  expect(globMatch("src/**/*.ts", "src/a/b/index.ts")).toBe(true);
  expect(globMatch("**/*.test.ts", "test/domain/regex.test.ts")).toBe(true);
  expect(globMatch("src/**", "src/a/b/c")).toBe(true);
  expect(globMatch("src/**", "lib/a")).toBe(false);
});

test("question mark matches one character", () => {
  expect(globMatch("v?.ts", "v1.ts")).toBe(true);
  expect(globMatch("v?.ts", "v12.ts")).toBe(false);
});

test("exact and negative", () => {
  expect(globMatch("package.json", "package.json")).toBe(true);
  expect(globMatch("package.json", "tsconfig.json")).toBe(false);
});

test("many doublestars stay polynomial and correct", () => {
  // Without memoizing the ** branch this is exponential in the number of **.
  const glob = "**/**/**/**/**/**/x";
  const path = Array.from({ length: 20 }, (_, i) => `s${i}`).join("/");
  const start = Bun.nanoseconds();
  expect(globMatch(glob, path)).toBe(false); // no trailing "x"
  expect(globMatch(glob, `${path}/x`)).toBe(true);
  const ms = (Bun.nanoseconds() - start) / 1e6;
  expect(ms).toBeLessThan(100);
});
