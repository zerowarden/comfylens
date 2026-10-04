import { useEffect, useMemo, useState } from "react";

import { fileUrl } from "../../api/client";
import type { DetailLora, ImageDetail } from "../../api/types";
import { familyColor } from "../../lib/colors";
import { compareFields, compareLoras, strengthLabel } from "../../lib/compare";
import { side, wordDiff, type Segment } from "../../lib/diff";
import { useImageDetail } from "../../lib/images";
import { useUi } from "../../state/ui";
import { chainKind } from "../../lib/chains";
import { ChainText } from "../icons";
import { Button, CloseButton, Message, td, th } from "../ui";

const name = (d: ImageDetail) => d.file.rel_path.split("/").pop() ?? d.file.rel_path;

function Caption({ id, d }: { id: number; d: ImageDetail | undefined }) {
  const family = d?.generation?.model_family ?? null;
  return (
    <div className="flex min-w-0 items-center gap-2 px-2 py-1 text-xs">
      <span
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ background: familyColor(family) }}
      />
      <span className="font-medium">#{id}</span>
      <span className="truncate text-zinc-500" title={d?.file.rel_path}>
        {d ? name(d) : "…"}
      </span>
    </div>
  );
}

function ImageCell({ id }: { id: number }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-black">
      {/* Both images fill their pane, so a small one is not dwarfed by its counterpart. */}
      <img src={fileUrl(id)} alt="" className="h-full w-full object-contain" />
    </div>
  );
}

/** Marks a differing row without relying on colour alone. */
function DiffMark({ differs }: { differs: boolean }) {
  return (
    <span className="inline-block w-3 text-amber-600" aria-label={differs ? "differs" : undefined}>
      {differs ? "≠" : ""}
    </span>
  );
}

const rowClass = (differs: boolean) => (differs ? "bg-amber-500/10" : "");

function Settings({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  const rows = compareFields(a, b);
  const shown = onlyDiff ? rows.filter((r) => r.differs) : rows;
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-zinc-500">
        Settings ({rows.filter((r) => r.differs).length} of {rows.length} differ)
      </h3>
      {shown.length === 0 ? (
        <div className="text-xs text-zinc-500">No differences in these settings.</div>
      ) : (
        <table className="w-full table-fixed text-xs">
          <thead>
            <tr>
              <th className={`${th} w-36`}>field</th>
              <th className={th}>A</th>
              <th className={th}>B</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const kind = chainKind(r.label);
              const cell = (v: string) => (kind ? <ChainText text={v} kind={kind} /> : v);
              return (
                <tr key={r.label} className={rowClass(r.differs)}>
                  <td className={`${td} text-zinc-500`}>
                    <DiffMark differs={r.differs} />
                    {r.label}
                  </td>
                  <td className={`${td} break-all`}>{cell(r.a)}</td>
                  <td className={`${td} break-all`}>{cell(r.b)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function UnusedList({ loras }: { loras: DetailLora[] }) {
  if (loras.length === 0) return <div className="text-zinc-500">none</div>;
  return (
    <ul className="space-y-0.5">
      {loras.map((l) => (
        <li key={`${l.node_id}:${l.entry}`} className="break-all">
          node {l.node_id}: {l.name} ({strengthLabel(l)})
        </li>
      ))}
    </ul>
  );
}

function Loras({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  const { chain, unusedA, unusedB } = compareLoras(a, b);
  const shown = onlyDiff ? chain.filter((r) => r.differs) : chain;
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-zinc-500">LoRA chains</h3>
      {chain.length === 0 ? (
        <div className="text-xs text-zinc-500">Neither image applies a LoRA.</div>
      ) : shown.length === 0 ? (
        <div className="text-xs text-zinc-500">Both images apply the same LoRAs.</div>
      ) : (
        <table className="w-full table-fixed text-xs">
          <thead>
            <tr>
              <th className={`${th} w-36`}>LoRA</th>
              <th className={th}>A strength</th>
              <th className={th}>B strength</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.name}:${i}`} className={rowClass(r.differs)}>
                <td className={`${td} break-all`}>
                  <DiffMark differs={r.differs} />
                  {r.name}
                </td>
                <td className={td}>{r.a ?? <span className="text-zinc-500">not applied</span>}</td>
                <td className={td}>{r.b ?? <span className="text-zinc-500">not applied</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(unusedA.length > 0 || unusedB.length > 0) && (
        <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
          <div>
            <div className="font-semibold text-amber-600">Unused LoRAs in A</div>
            <UnusedList loras={unusedA} />
          </div>
          <div>
            <div className="font-semibold text-amber-600">Unused LoRAs in B</div>
            <UnusedList loras={unusedB} />
          </div>
        </div>
      )}
    </section>
  );
}

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.kind === "removed" ? (
          <del
            key={i}
            title="Only in A"
            className="rounded-sm bg-red-500/20 text-red-800 decoration-2 dark:text-red-200"
          >
            {s.text}
          </del>
        ) : s.kind === "added" ? (
          <ins
            key={i}
            title="Only in B"
            className="rounded-sm bg-emerald-500/20 text-emerald-800 underline decoration-2 underline-offset-2 dark:text-emerald-200"
          >
            {s.text}
          </ins>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}

/** One side of a prompt: its diff segments, or a note when there is no text to show. */
function PromptText({ text, segments }: { text: string | null; segments: Segment[] | null }) {
  if (text === null) return <span className="text-zinc-500">(no prompt)</span>;
  if (text.trim() === "") return <span className="text-zinc-500">(empty)</span>;
  return segments ? <Segments segments={segments} /> : <>{text}</>;
}

function PromptDiff({ label, a, b }: { label: string; a: string | null; b: string | null }) {
  const diff = useMemo(() => (a !== null && b !== null ? wordDiff(a, b) : null), [a, b]);
  if (a === null && b === null) return null;
  const changed = diff ? diff.ops.some((op) => op.kind !== "same") : true;
  const box = "rounded bg-zinc-100 p-2 font-sans break-words whitespace-pre-wrap dark:bg-zinc-900";
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold text-zinc-500">
        {label} ({changed ? "differs" : "identical words"})
      </h3>
      {diff?.coarse && (
        <div className="mb-1 text-xs text-zinc-500">
          Too long to align word by word: the differing middle is marked as a whole.
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 text-xs">
        <pre className={box}>
          <PromptText text={a} segments={diff ? side(diff, "a") : null} />
        </pre>
        <pre className={box}>
          <PromptText text={b} segments={diff ? side(diff, "b") : null} />
        </pre>
      </div>
    </section>
  );
}

function Comparison({ a, b, onlyDiff }: { a: ImageDetail; b: ImageDetail; onlyDiff: boolean }) {
  const ga = a.generation;
  const gb = b.generation;
  return (
    <div className="space-y-4 p-3">
      <Settings a={a} b={b} onlyDiff={onlyDiff} />
      <Loras a={a} b={b} onlyDiff={onlyDiff} />
      <div className="text-xs text-zinc-500">
        Prompt words: <del className="decoration-2">struck through</del> only in A,{" "}
        <ins className="underline decoration-2 underline-offset-2">underlined</ins> only in B.
        Whitespace changes are ignored.
      </div>
      <PromptDiff
        label="Positive prompt"
        a={ga?.positive_prompt ?? null}
        b={gb?.positive_prompt ?? null}
      />
      <PromptDiff
        label="Negative prompt"
        a={ga?.negative_prompt ?? null}
        b={gb?.negative_prompt ?? null}
      />
    </div>
  );
}

/** Two selected images side by side: settings, LoRA chains and a word-level prompt diff. */
export default function CompareView() {
  const ids = useUi((s) => s.compareIds);
  const openCompare = useUi((s) => s.openCompare);
  const detailOpen = useUi((s) => s.detailId !== null);

  useEffect(() => {
    if (ids === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !detailOpen) openCompare(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ids, detailOpen, openCompare]);

  if (ids === null) return null;
  return <Modal ids={ids} onClose={() => openCompare(null)} />;
}

function Modal({ ids, onClose }: { ids: [number, number]; onClose: () => void }) {
  const [idA, idB] = ids;
  const a = useImageDetail(idA);
  const b = useImageDetail(idB);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const error = a.error ?? b.error;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Compare two images"
        className="flex h-[90vh] w-[90vw] flex-col overflow-hidden rounded-lg bg-white shadow-2xl dark:bg-zinc-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
          <span className="font-medium">Compare</span>
          <span className="text-xs text-zinc-500">
            A #{idA}, B #{idB}
          </span>
          <span className="flex-1" />
          <Button active={onlyDiff} onClick={() => setOnlyDiff(!onlyDiff)}>
            Only differences
          </Button>
          <CloseButton onClick={onClose} />
        </div>
        <div className="grid h-[38%] shrink-0 grid-cols-2 gap-px border-b border-zinc-200 bg-zinc-200 dark:border-zinc-800 dark:bg-zinc-800">
          {[
            { id: idA, d: a.data },
            { id: idB, d: b.data },
          ].map(({ id, d }) => (
            <div key={id} className="flex min-h-0 flex-col bg-white dark:bg-zinc-950">
              <Caption id={id} d={d} />
              <ImageCell id={id} />
            </div>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {a.data && b.data ? (
            <Comparison a={a.data} b={b.data} onlyDiff={onlyDiff} />
          ) : (
            <Message>{error ? error.message : "Loading…"}</Message>
          )}
        </div>
      </div>
    </div>
  );
}
