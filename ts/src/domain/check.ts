// The lexical check language (ARCHITECTURE.md section 5.1).
//
// Quantifier-free formulas (and / or / not) over atoms from a closed set. A
// check evaluates over one FactRecord, purely and totally: it reads only the
// assembled facts, never the filesystem, network, or clock. An absent fact
// makes an atom false rather than throwing, so evaluation is total.

import { type FactRecord, type FieldRef, resolveField } from "./facts.ts";
import { globMatch } from "./glob.ts";
import { regexError, regexTest } from "./regex.ts";

export type Atom =
  | { readonly op: "bool.eq"; readonly field: FieldRef; readonly value: boolean }
  | { readonly op: "enum.eq"; readonly field: FieldRef; readonly value: string }
  | {
      readonly op: "enum.in";
      readonly field: FieldRef;
      readonly values: readonly string[];
    }
  | { readonly op: "int.eq"; readonly field: FieldRef; readonly value: number }
  | {
      readonly op: "int.cmp";
      readonly field: FieldRef;
      readonly cmp: "lt" | "le" | "gt" | "ge";
      readonly value: number;
    }
  | { readonly op: "str.eq"; readonly field: FieldRef; readonly value: string }
  | {
      readonly op: "str.in";
      readonly field: FieldRef;
      readonly values: readonly string[];
    }
  | { readonly op: "str.prefix"; readonly field: FieldRef; readonly value: string }
  | { readonly op: "str.suffix"; readonly field: FieldRef; readonly value: string }
  | {
      readonly op: "str.contains";
      readonly field: FieldRef;
      readonly value: string;
    }
  | { readonly op: "str.regex"; readonly field: FieldRef; readonly pattern: string }
  | { readonly op: "path.glob"; readonly field: FieldRef; readonly glob: string };

export type Check =
  | { readonly op: "and"; readonly checks: readonly Check[] }
  | { readonly op: "or"; readonly checks: readonly Check[] }
  | { readonly op: "not"; readonly check: Check }
  | Atom;

/** Evaluate a check against a fact record. Pure and total. */
export function evaluate(check: Check, facts: FactRecord): boolean {
  switch (check.op) {
    case "and":
      return check.checks.every((c) => evaluate(c, facts));
    case "or":
      return check.checks.some((c) => evaluate(c, facts));
    case "not":
      return !evaluate(check.check, facts);
    default:
      return evalAtom(check, facts);
  }
}

function evalAtom(atom: Atom, facts: FactRecord): boolean {
  // Bounds-check the input despite authoring-time validation (ARCHITECTURE 6.4,
  // the CrowdStrike lesson): a malformed atom degrades to false, never throws.
  if (atom.field === undefined || typeof atom.field !== "object") return false;
  const v = resolveField(facts, atom.field);
  switch (atom.op) {
    case "bool.eq":
      return typeof v === "boolean" && v === atom.value;
    case "enum.eq":
    case "str.eq":
      return typeof v === "string" && v === atom.value;
    case "enum.in":
    case "str.in":
      return typeof v === "string" && atom.values.includes(v);
    case "int.eq":
      return typeof v === "number" && v === atom.value;
    case "int.cmp": {
      if (typeof v !== "number") return false;
      switch (atom.cmp) {
        case "lt":
          return v < atom.value;
        case "le":
          return v <= atom.value;
        case "gt":
          return v > atom.value;
        case "ge":
          return v >= atom.value;
        default:
          return false;
      }
    }
    case "str.prefix":
      return typeof v === "string" && v.startsWith(atom.value);
    case "str.suffix":
      return typeof v === "string" && v.endsWith(atom.value);
    case "str.contains":
      return typeof v === "string" && v.includes(atom.value);
    case "str.regex":
      return typeof v === "string" && regexTest(atom.pattern, v);
    case "path.glob":
      return typeof v === "string" && globMatch(atom.glob, v);
    default:
      return false;
  }
}

const FIELD_KINDS = new Set([
  "tool",
  "input",
  "path",
  "repository",
  "branch",
  "permissionMode",
]);

const STRING_OPS = new Set(["str.eq", "enum.eq", "str.prefix", "str.suffix", "str.contains"]);
const STRING_ARRAY_OPS = new Set(["str.in", "enum.in"]);

/**
 * Full well-formedness check at authoring time (ARCHITECTURE 5.1, N5). Because
 * a check is parsed from card JSON that a hand-edit or a model could corrupt,
 * this validates the whole shape, not just regex compilation: a known operator,
 * a valid field reference, and the operator's required, correctly typed fields.
 * Returns null if valid, else the first problem.
 */
export function checkError(check: unknown): string | null {
  if (typeof check !== "object" || check === null) return "check is not an object";
  const c = check as Record<string, unknown>;
  const op = c.op;
  if (typeof op !== "string") return "check has no op";

  if (op === "and" || op === "or") {
    if (!Array.isArray(c.checks)) return `${op} requires a checks array`;
    for (const sub of c.checks) {
      const e = checkError(sub);
      if (e !== null) return e;
    }
    return null;
  }
  if (op === "not") {
    return checkError(c.check);
  }

  const fieldErr = fieldError(c.field);
  if (fieldErr !== null) return fieldErr;

  if (op === "bool.eq") return typeof c.value === "boolean" ? null : "bool.eq needs a boolean value";
  if (op === "int.eq") return typeof c.value === "number" ? null : "int.eq needs a number value";
  if (op === "int.cmp") {
    if (typeof c.value !== "number") return "int.cmp needs a number value";
    return ["lt", "le", "gt", "ge"].includes(c.cmp as string) ? null : "int.cmp needs cmp in lt|le|gt|ge";
  }
  if (STRING_OPS.has(op)) return typeof c.value === "string" ? null : `${op} needs a string value`;
  if (STRING_ARRAY_OPS.has(op)) {
    return Array.isArray(c.values) && c.values.every((v) => typeof v === "string")
      ? null
      : `${op} needs a string[] values`;
  }
  if (op === "str.regex") {
    if (typeof c.pattern !== "string") return "str.regex needs a string pattern";
    const e = regexError(c.pattern);
    return e === null ? null : `invalid regex /${c.pattern}/: ${e}`;
  }
  if (op === "path.glob") return typeof c.glob === "string" ? null : "path.glob needs a string glob";
  return `unknown check op '${op}'`;
}

function fieldError(field: unknown): string | null {
  if (typeof field !== "object" || field === null) return "atom has no field";
  const f = field as Record<string, unknown>;
  if (typeof f.kind !== "string" || !FIELD_KINDS.has(f.kind)) {
    return `invalid field kind '${String(f.kind)}'`;
  }
  if (f.kind === "input" && typeof f.key !== "string") {
    return "input field needs a string key";
  }
  return null;
}
