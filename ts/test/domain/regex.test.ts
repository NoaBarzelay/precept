import { expect, test } from "bun:test";
import { regexError, regexTest } from "../../src/domain/regex.ts";

test("literals and unanchored search", () => {
  expect(regexTest("pip", "pip install x")).toBe(true);
  expect(regexTest("pip", "uv pip install x")).toBe(true);
  expect(regexTest("pip", "poetry add x")).toBe(false);
});

test("dot, star, plus, opt", () => {
  expect(regexTest("a.c", "abc")).toBe(true);
  expect(regexTest("a.c", "ac")).toBe(false);
  expect(regexTest("ab*c", "ac")).toBe(true);
  expect(regexTest("ab*c", "abbbc")).toBe(true);
  expect(regexTest("ab+c", "ac")).toBe(false);
  expect(regexTest("ab+c", "abc")).toBe(true);
  expect(regexTest("ab?c", "ac")).toBe(true);
  expect(regexTest("ab?c", "abc")).toBe(true);
  expect(regexTest("ab?c", "abbc")).toBe(false);
});

test("alternation and groups", () => {
  expect(regexTest("(cat|dog)s", "cats")).toBe(true);
  expect(regexTest("(cat|dog)s", "dogs")).toBe(true);
  expect(regexTest("(cat|dog)s", "fishs")).toBe(false);
});

test("character classes", () => {
  expect(regexTest("[a-z]+", "hello")).toBe(true);
  expect(regexTest("^[a-z]+$", "hello5")).toBe(false);
  expect(regexTest("[^0-9]", "a")).toBe(true);
  expect(regexTest("[^0-9]", "5")).toBe(false);
});

test("escapes \\d \\w \\s", () => {
  expect(regexTest("\\d+", "abc123")).toBe(true);
  expect(regexTest("^\\d+$", "abc123")).toBe(false);
  expect(regexTest("\\w+", "under_score")).toBe(true);
  expect(regexTest("a\\sb", "a b")).toBe(true);
  expect(regexTest("\\.", "a.b")).toBe(true);
  expect(regexTest("\\.", "axb")).toBe(false);
});

test("anchors", () => {
  expect(regexTest("^pip", "pip install")).toBe(true);
  expect(regexTest("^pip", "uv pip install")).toBe(false);
  expect(regexTest("install$", "pip install")).toBe(true);
  expect(regexTest("install$", "install x")).toBe(false);
});

test("linear time on a would-be-catastrophic pattern", () => {
  // (a+)+$ against a long non-matching string is the classic ReDoS. A
  // backtracking engine hangs; the NFA simulation stays linear.
  const evil = "(a+)+$";
  const input = "a".repeat(40) + "!";
  const start = Bun.nanoseconds();
  const result = regexTest(evil, input);
  const ms = (Bun.nanoseconds() - start) / 1e6;
  expect(result).toBe(false);
  expect(ms).toBeLessThan(50);
});

test("authoring-time validation rejects malformed patterns", () => {
  expect(regexError("a(b")).not.toBeNull();
  expect(regexError("a[b")).not.toBeNull();
  expect(regexError("*abc")).not.toBeNull();
  expect(regexError("pip install")).toBeNull();
  expect(regexError("(cat|dog)s?")).toBeNull();
});
