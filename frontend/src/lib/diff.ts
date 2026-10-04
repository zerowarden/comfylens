/**
 * Word-level text diff for comparing two prompts.
 *
 * Text is split into words, whitespace runs and single punctuation marks. Whitespace runs
 * compare equal to each other, so a re-wrapped line is not a change: only words and
 * punctuation are diffed. Each side keeps its own whitespace for display.
 */

export type DiffKind = "same" | "removed" | "added";

/** A run of tokens; `a` and `b` are its text on each side ("" where it is absent). */
export interface DiffOp {
  kind: DiffKind;
  a: string;
  b: string;
}

/** A run of one side's text, for display. */
export interface Segment {
  kind: DiffKind;
  text: string;
}

export interface WordDiff {
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
export const MAX_CELLS = 4_000_000;

export function wordDiff(a: string, b: string, maxCells: number = MAX_CELLS): WordDiff {
  const ta = tokenize(a);
  const tb = tokenize(b);

  // A shared prefix and suffix need no alignment, and often leave little in between.
  let start = 0;
  while (start < ta.length && start < tb.length && same(ta[start]!, tb[start]!)) start++;
  let endA = ta.length;
  let endB = tb.length;
  while (endA > start && endB > start && same(ta[endA - 1]!, tb[endB - 1]!)) {
    endA--;
    endB--;
  }

  const ops: DiffOp[] = [];
  for (let i = 0; i < start; i++) push(ops, { kind: "same", a: ta[i]!, b: tb[i]! });
  const midA = ta.slice(start, endA);
  const midB = tb.slice(start, endB);
  let coarse = false;
  if ((midA.length + 1) * (midB.length + 1) > maxCells) {
    coarse = true;
    for (const t of midA) push(ops, { kind: "removed", a: t, b: "" });
    for (const t of midB) push(ops, { kind: "added", a: "", b: t });
  } else {
    for (const op of align(midA, midB)) push(ops, op);
  }
  for (let i = 0; i < ta.length - endA; i++) {
    push(ops, { kind: "same", a: ta[endA + i]!, b: tb[endB + i]! });
  }
  return { ops, coarse };
}

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
  const out: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (same(a[i]!, b[j]!)) {
      out.push({ kind: "same", a: a[i++]!, b: b[j++]! });
    } else if (lcs[(i + 1) * width + j]! >= lcs[i * width + j + 1]!) {
      out.push({ kind: "removed", a: a[i++]!, b: "" });
    } else {
      out.push({ kind: "added", a: "", b: b[j++]! });
    }
  }
  while (i < n) out.push({ kind: "removed", a: a[i++]!, b: "" });
  while (j < m) out.push({ kind: "added", a: "", b: b[j++]! });
  return out;
}

/** Append, merging with the previous run of the same kind. */
function push(ops: DiffOp[], op: DiffOp): void {
  const last = ops.at(-1);
  if (last && last.kind === op.kind) {
    last.a += op.a;
    last.b += op.b;
  } else ops.push({ ...op });
}

/** One side for display: A shows its "same" and "removed" runs, B its "same" and "added". */
export function side(diff: WordDiff, which: "a" | "b"): Segment[] {
  const out: Segment[] = [];
  for (const op of diff.ops) {
    const text = which === "a" ? op.a : op.b;
    if (!text) continue;
    const last = out.at(-1);
    if (last && last.kind === op.kind) last.text += text;
    else out.push({ kind: op.kind, text });
  }
  return out;
}

/** Whether two texts differ in words or punctuation (whitespace alone does not count). */
export function textsDiffer(a: string, b: string): boolean {
  return wordDiff(a, b).ops.some((op) => op.kind !== "same");
}
