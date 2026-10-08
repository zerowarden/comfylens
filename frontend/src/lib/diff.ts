/**
 * Word-level text diff for comparing two prompts.
 *
 * Text is split into words, whitespace runs and single punctuation marks. Whitespace runs
 * compare equal to each other, so a re-wrapped line is not a change: only words and
 * punctuation are diffed. Each side keeps its own whitespace for display.
 */

type DiffKind = "same" | "removed" | "added";

/** A run of tokens; `a` and `b` are its text on each side ("" where it is absent). */
interface DiffOp {
  kind: DiffKind;
  a: string;
  b: string;
}

/** A run of one side's text, for display. */
export interface Segment {
  kind: DiffKind;
  text: string;
}

interface WordDiff {
  /** Runs in order: "same", "removed" (only in A) and "added" (only in B). */
  ops: DiffOp[];
  /** True when the texts were too long to align word by word: the differing middle is shown
   * as one removed block and one added block. */
  coarse: boolean;
}

const TOKEN = /[\p{L}\p{N}_'’-]+|\s+|[^\p{L}\p{N}_'’\s-]/gu;

export function tokenize(text: string): string[] {
  return text.match(TOKEN) ?? [];
}

const isSpace = (t: string) => /^\s+$/.test(t);
const same = (a: string, b: string) => a === b || (isSpace(a) && isSpace(b));

/** Default budget for the alignment table: 4 million cells, about 16 MB. */
const MAX_CELLS = 4_000_000;

export function wordDiff(a: string, b: string, maxCells: number = MAX_CELLS): WordDiff {
  const ta = tokenize(a);
  const tb = tokenize(b);
  // A shared prefix and suffix need no alignment, and often leave little in between.
  const start = sharedPrefix(ta, tb);
  const end = sharedPrefix(ta.slice(start).reverse(), tb.slice(start).reverse());
  const midA = ta.slice(start, ta.length - end);
  const midB = tb.slice(start, tb.length - end);
  const coarse = (midA.length + 1) * (midB.length + 1) > maxCells;
  const middle = coarse ? [...runs("removed", midA), ...runs("added", midB)] : align(midA, midB);
  const ops = [
    ...sameRuns(ta.slice(0, start), tb),
    ...middle,
    ...sameRuns(ta.slice(ta.length - end), tb.slice(tb.length - end)),
  ];
  return { ops: joinRuns(ops, (x, y) => ({ kind: x.kind, a: x.a + y.a, b: x.b + y.b })), coarse };
}

/** How many leading tokens two lists share. */
function sharedPrefix(a: string[], b: string[]): number {
  const length = Math.min(a.length, b.length);
  const first = a.findIndex((t, i) => i >= length || !same(t, b[i]!));
  return first < 0 ? length : first;
}

/** One run per token of one side. */
const runs = (kind: "removed" | "added", tokens: string[]): DiffOp[] =>
  tokens.map((t) => (kind === "removed" ? { kind, a: t, b: "" } : { kind, a: "", b: t }));

/** Tokens the two sides share, pairwise. */
const sameRuns = (a: string[], b: string[]): DiffOp[] =>
  a.map((t, i) => ({ kind: "same", a: t, b: b[i]! }));

/** Longest-common-subsequence alignment of two token lists. */
function align(a: string[], b: string[]): DiffOp[] {
  const n = a.length;
  const m = b.length;
  const width = m + 1;
  // lcs[i * width + j]: LCS length of a[i:] and b[j:].
  const lcs = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i * width + j] = same(a[i]!, b[j]!)
        ? lcs[(i + 1) * width + j + 1]! + 1
        : Math.max(lcs[(i + 1) * width + j]!, lcs[i * width + j + 1]!);
    }
  }
  /** The step from a[i:] and b[j:] that keeps the longest common subsequence. */
  const step = (i: number, j: number): DiffKind => {
    if (i === n) return "added";
    if (j === m) return "removed";
    if (same(a[i]!, b[j]!)) return "same";
    return lcs[(i + 1) * width + j]! >= lcs[i * width + j + 1]! ? "removed" : "added";
  };
  const out: DiffOp[] = [];
  for (let i = 0, j = 0; i < n || j < m;) {
    const kind = step(i, j);
    out.push({ kind, a: kind === "added" ? "" : a[i++]!, b: kind === "removed" ? "" : b[j++]! });
  }
  return out;
}

/** Adjacent runs of the same kind joined into one. */
function joinRuns<T extends { kind: DiffKind }>(items: T[], join: (x: T, y: T) => T): T[] {
  return items.reduce<T[]>((out, item) => {
    const last = out.at(-1);
    if (last?.kind === item.kind) out[out.length - 1] = join(last, item);
    else out.push(item);
    return out;
  }, []);
}

/** One side for display: A shows its "same" and "removed" runs, B its "same" and "added". */
export function side(diff: WordDiff, which: "a" | "b"): Segment[] {
  const segments = diff.ops.map((op) => ({ kind: op.kind, text: op[which] })).filter((s) => s.text);
  return joinRuns(segments, (x, y) => ({ kind: x.kind, text: x.text + y.text }));
}

/** Whether two texts differ in words or punctuation (whitespace alone does not count). */
export function textsDiffer(a: string, b: string): boolean {
  return wordDiff(a, b).ops.some((op) => op.kind !== "same");
}
