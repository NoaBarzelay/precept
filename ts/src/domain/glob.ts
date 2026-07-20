// Glob matching over path segments (ARCHITECTURE.md section 5.1: Path atoms are
// "glob over segments"). Memoized so it stays polynomial, no exponential
// backtracking.
//
//   *   matches any run of characters within a single segment (not "/")
//   ?   matches one character within a segment (not "/")
//   **  as a whole segment, matches zero or more path segments

/** True if `glob` matches `path`. Both are "/"-separated. */
export function globMatch(glob: string, path: string): boolean {
  const g = glob.split("/");
  const p = path.split("/");
  const memo = new Map<string, boolean>();

  function seg(gi: number, pi: number): boolean {
    if (gi === g.length) return pi === p.length;
    const gs = g[gi]!;
    if (gs === "**") {
      // Match zero or more path segments.
      for (let k = pi; k <= p.length; k++) {
        if (seg(gi + 1, k)) return true;
      }
      return false;
    }
    if (pi === p.length) return false;
    const key = `${gi},${pi}`;
    const cached = memo.get(key);
    if (cached !== undefined) return cached;
    const ok = matchSegment(gs, p[pi]!) && seg(gi + 1, pi + 1);
    memo.set(key, ok);
    return ok;
  }

  return seg(0, 0);
}

/** Match a single glob segment (no "**") against one path segment. */
function matchSegment(glob: string, s: string): boolean {
  const memo = new Map<string, boolean>();
  function m(gi: number, si: number): boolean {
    if (gi === glob.length) return si === s.length;
    const key = `${gi},${si}`;
    const cached = memo.get(key);
    if (cached !== undefined) return cached;
    const c = glob[gi]!;
    let ok: boolean;
    if (c === "*") {
      // zero or more chars within the segment
      ok = false;
      for (let k = si; k <= s.length; k++) {
        if (m(gi + 1, k)) {
          ok = true;
          break;
        }
      }
    } else if (c === "?") {
      ok = si < s.length && m(gi + 1, si + 1);
    } else {
      ok = si < s.length && s[si] === c && m(gi + 1, si + 1);
    }
    memo.set(key, ok);
    return ok;
  }
  return m(0, 0);
}
