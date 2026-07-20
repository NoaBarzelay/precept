// The fact base for the lexical check tier (ARCHITECTURE.md section 5.1).
//
// A check is a formula over one immutable, typed record assembled before
// evaluation. It may reference only: the tool name; the typed fields of that
// tool's input; the resolved path, repository, and branch; and the session's
// permission mode. Facts are collected first, then the formula is evaluated,
// so evaluation is pure and total.

export type PermissionMode =
  | "default"
  | "acceptEdits"
  | "bypassPermissions"
  | "plan";

export const PERMISSION_MODES: readonly PermissionMode[] = [
  "default",
  "acceptEdits",
  "bypassPermissions",
  "plan",
];

/** A tool-input field value. The lexical tier reasons over scalars only. */
export type FactValue = string | number | boolean;

export interface FactRecord {
  /** The tool being called, e.g. "Bash", "Edit". */
  readonly toolName: string;
  /** The tool's typed input fields, e.g. { command: "pip install x" }. */
  readonly toolInput: Readonly<Record<string, FactValue>>;
  /** Resolved absolute path the call touches, if any. */
  readonly path?: string;
  /** Resolved repository name, if the call is inside one. */
  readonly repository?: string;
  /** Resolved git branch, if the call is inside a repository. */
  readonly branch?: string;
  /** The session's permission mode at the time of the call. */
  readonly permissionMode: PermissionMode;
}

/** A reference to one fact in the record. */
export type FieldRef =
  | { readonly kind: "tool" }
  | { readonly kind: "input"; readonly key: string }
  | { readonly kind: "path" }
  | { readonly kind: "repository" }
  | { readonly kind: "branch" }
  | { readonly kind: "permissionMode" };

/** Resolve a field to its value, or undefined when the fact is absent. */
export function resolveField(
  facts: FactRecord,
  ref: FieldRef,
): FactValue | undefined {
  switch (ref.kind) {
    case "tool":
      return facts.toolName;
    case "input":
      return facts.toolInput[ref.key];
    case "path":
      return facts.path;
    case "repository":
      return facts.repository;
    case "branch":
      return facts.branch;
    case "permissionMode":
      return facts.permissionMode;
  }
}
