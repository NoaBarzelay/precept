// A linear-time regular-expression matcher (ARCHITECTURE.md section 5.1:
// "evaluated by a linear-time engine only, never a backtracking one, so a
// model-authored pattern cannot cause a runtime denial of service").
//
// Thompson NFA construction plus subset simulation. Match time is O(n * m)
// in the input length n and pattern size m, with no backtracking, so there is
// no catastrophic-backtracking (ReDoS) class to guard against.
//
// Supported syntax (a deliberately small, common subset):
//   literals, . escapes (\d \w \s and \. etc.), character classes [a-z] [^...],
//   groups (...), alternation |, quantifiers * + ?, anchors ^ $.
// Not supported (by construction, since they need backtracking or captures):
//   backreferences, lookaround, non-greedy quantifiers, capture extraction.

type Node =
  | { t: "char"; test: (c: string) => boolean }
  | { t: "concat"; parts: Node[] }
  | { t: "alt"; opts: Node[] }
  | { t: "star"; node: Node }
  | { t: "plus"; node: Node }
  | { t: "opt"; node: Node }
  | { t: "empty" }
  | { t: "anchorStart" }
  | { t: "anchorEnd" };

class Parser {
  private i = 0;
  constructor(private readonly src: string) {}

  parse(): Node {
    const node = this.parseAlt();
    if (this.i < this.src.length) {
      throw new SyntaxError(`unexpected '${this.src[this.i]}' at ${this.i}`);
    }
    return node;
  }

  private peek(): string | undefined {
    return this.src[this.i];
  }
  private next(): string {
    const c = this.src[this.i];
    if (c === undefined) throw new SyntaxError("unexpected end of pattern");
    this.i++;
    return c;
  }

  private parseAlt(): Node {
    const opts = [this.parseConcat()];
    while (this.peek() === "|") {
      this.next();
      opts.push(this.parseConcat());
    }
    return opts.length === 1 ? opts[0]! : { t: "alt", opts };
  }

  private parseConcat(): Node {
    const parts: Node[] = [];
    for (;;) {
      const c = this.peek();
      if (c === undefined || c === "|" || c === ")") break;
      parts.push(this.parseQuantified());
    }
    if (parts.length === 0) return { t: "empty" };
    return parts.length === 1 ? parts[0]! : { t: "concat", parts };
  }

  private parseQuantified(): Node {
    let node = this.parseAtom();
    for (;;) {
      const c = this.peek();
      if (c === "*") {
        this.next();
        node = { t: "star", node };
      } else if (c === "+") {
        this.next();
        node = { t: "plus", node };
      } else if (c === "?") {
        this.next();
        node = { t: "opt", node };
      } else {
        break;
      }
    }
    return node;
  }

  private parseAtom(): Node {
    const c = this.next();
    if (c === "(") {
      const inner = this.parseAlt();
      if (this.next() !== ")") throw new SyntaxError("expected ')'");
      return inner;
    }
    if (c === "[") return this.parseClass();
    if (c === "^") return { t: "anchorStart" };
    if (c === "$") return { t: "anchorEnd" };
    if (c === ".") return { t: "char", test: (ch) => ch !== "\n" };
    if (c === "\\") return { t: "char", test: escapeClass(this.next()) };
    if (c === ")" || c === "*" || c === "+" || c === "?") {
      throw new SyntaxError(`unexpected '${c}'`);
    }
    return { t: "char", test: (ch) => ch === c };
  }

  private parseClass(): Node {
    let negate = false;
    if (this.peek() === "^") {
      this.next();
      negate = true;
    }
    const tests: Array<(c: string) => boolean> = [];
    while (this.peek() !== "]") {
      let lo = this.next();
      if (lo === "\\") lo = unescapeLiteral(this.next());
      if (this.peek() === "-" && this.src[this.i + 1] !== "]") {
        this.next(); // consume '-'
        let hi = this.next();
        if (hi === "\\") hi = unescapeLiteral(this.next());
        const a = lo.codePointAt(0)!;
        const b = hi.codePointAt(0)!;
        tests.push((ch) => {
          const p = ch.codePointAt(0)!;
          return p >= a && p <= b;
        });
      } else {
        const only = lo;
        tests.push((ch) => ch === only);
      }
      if (this.i >= this.src.length) throw new SyntaxError("unterminated class");
    }
    this.next(); // consume ']'
    return {
      t: "char",
      test: (ch) => {
        const hit = tests.some((f) => f(ch));
        return negate ? !hit : hit;
      },
    };
  }
}

function escapeClass(c: string): (ch: string) => boolean {
  switch (c) {
    case "d":
      return (ch) => ch >= "0" && ch <= "9";
    case "D":
      return (ch) => !(ch >= "0" && ch <= "9");
    case "w":
      return (ch) => /[A-Za-z0-9_]/.test(ch);
    case "W":
      return (ch) => !/[A-Za-z0-9_]/.test(ch);
    case "s":
      return (ch) => /\s/.test(ch);
    case "S":
      return (ch) => !/\s/.test(ch);
    case "n":
      return (ch) => ch === "\n";
    case "t":
      return (ch) => ch === "\t";
    case "r":
      return (ch) => ch === "\r";
    default:
      return (ch) => ch === c;
  }
}

function unescapeLiteral(c: string): string {
  switch (c) {
    case "n":
      return "\n";
    case "t":
      return "\t";
    case "r":
      return "\r";
    default:
      return c;
  }
}

// Compile the AST to an NFA of states with epsilon transitions. Each state is
// either an accept, a char matcher with one out-edge, or a split of up to two
// epsilon edges. States are indices into `chars` and `splits`.

interface Nfa {
  start: number;
  accept: number;
  chars: Map<number, { test: (c: string) => boolean; out: number }>;
  splits: Map<number, number[]>;
  anchorStart: Set<number>;
  anchorEnd: Set<number>;
}

class Builder {
  chars = new Map<number, { test: (c: string) => boolean; out: number }>();
  splits = new Map<number, number[]>();
  anchorStart = new Set<number>();
  anchorEnd = new Set<number>();
  private n = 0;

  state(): number {
    return this.n++;
  }

  // Build a fragment [start, out-placeholder]; returns {start, patch}
  // where patch sets the fragment's dangling edge to a target state.
  build(node: Node, out: number): number {
    switch (node.t) {
      case "empty":
        return out;
      case "char": {
        const s = this.state();
        this.chars.set(s, { test: node.test, out });
        return s;
      }
      case "anchorStart": {
        const s = this.state();
        this.anchorStart.add(s);
        this.splits.set(s, [out]);
        return s;
      }
      case "anchorEnd": {
        const s = this.state();
        this.anchorEnd.add(s);
        this.splits.set(s, [out]);
        return s;
      }
      case "concat": {
        let next = out;
        for (let k = node.parts.length - 1; k >= 0; k--) {
          next = this.build(node.parts[k]!, next);
        }
        return next;
      }
      case "alt": {
        const s = this.state();
        this.splits.set(
          s,
          node.opts.map((o) => this.build(o, out)),
        );
        return s;
      }
      case "opt": {
        const s = this.state();
        const inner = this.build(node.node, out);
        this.splits.set(s, [inner, out]);
        return s;
      }
      case "star": {
        const s = this.state();
        const inner = this.build(node.node, s);
        this.splits.set(s, [inner, out]);
        return s;
      }
      case "plus": {
        const s = this.state();
        const inner = this.build(node.node, s);
        this.splits.set(s, [inner, out]);
        // enter the inner at least once
        return inner;
      }
    }
  }
}

function compile(pattern: string): Nfa {
  const ast = new Parser(pattern).parse();
  const b = new Builder();
  const accept = b.state();
  const start = b.build(ast, accept);
  return {
    start,
    accept,
    chars: b.chars,
    splits: b.splits,
    anchorStart: b.anchorStart,
    anchorEnd: b.anchorEnd,
  };
}

const cache = new Map<string, Nfa>();

/**
 * True if `pattern` matches anywhere in `input`. A single-pass NFA simulation:
 * one left-to-right sweep, seeding the start state at every position for the
 * unanchored search, so match time is O(n * m) in the input length n and NFA
 * size m, with no backtracking. Throws SyntaxError on a malformed pattern.
 */
export function regexTest(pattern: string, input: string): boolean {
  let nfa = cache.get(pattern);
  if (nfa === undefined) {
    nfa = compile(pattern);
    cache.set(pattern, nfa);
  }
  const end = input.length;
  let current = new Set<number>();
  addState(nfa, nfa.start, current, 0, end);
  if (current.has(nfa.accept)) return true;

  for (let pos = 0; pos < end; pos++) {
    const ch = input[pos]!;
    const next = new Set<number>();
    for (const s of current) {
      const c = nfa.chars.get(s);
      if (c !== undefined && c.test(ch)) {
        addState(nfa, c.out, next, pos + 1, end);
      }
    }
    // Seed a fresh start here: the implicit unanchored prefix. anchorStart is
    // pruned at pos+1 != 0, so `^` still only matches at position 0.
    addState(nfa, nfa.start, next, pos + 1, end);
    current = next;
    if (current.has(nfa.accept)) return true;
  }
  return current.has(nfa.accept);
}

/** Validate a pattern at authoring time. Returns null if valid, else message. */
export function regexError(pattern: string): string | null {
  try {
    compile(pattern);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

// Epsilon-closure that respects anchors. `pos` is the input position at which
// the states are entered; `end` is the input length.
function addState(
  nfa: Nfa,
  s: number,
  set: Set<number>,
  pos: number,
  end: number,
): void {
  if (set.has(s)) return;
  if (nfa.anchorStart.has(s) && pos !== 0) return;
  if (nfa.anchorEnd.has(s) && pos !== end) return;
  set.add(s);
  const outs = nfa.splits.get(s);
  if (outs !== undefined) {
    for (const o of outs) addState(nfa, o, set, pos, end);
  }
}
