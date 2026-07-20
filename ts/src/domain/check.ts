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
  }
}

/**
 * Well-formedness check at authoring time: reject a check whose regex atoms do
 * not compile. Structural type-correctness is guaranteed by the discriminated
 * union; this catches the one runtime-parseable field. Returns null if valid.
 */
export function checkError(check: Check): string | null {
  switch (check.op) {
    case "and":
    case "or":
      for (const c of check.checks) {
        const e = checkError(c);
        if (e !== null) return e;
      }
      return null;
    case "not":
      return checkError(check.check);
    case "str.regex": {
      const e = regexError(check.pattern);
      return e === null ? null : `invalid regex /${check.pattern}/: ${e}`;
    }
    default:
      return null;
  }
}
