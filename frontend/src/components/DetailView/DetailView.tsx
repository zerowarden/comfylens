import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { api, fileUrl } from "../../api/client";
import type { ImageDetail } from "../../api/types";
import { settingsRows } from "../../lib/compare";
import { fmtBytes, fmtNum } from "../../lib/format";
import { useImageDetail, useImageOrder } from "../../lib/images";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { chainKind } from "../../lib/chains";
import { ChainText, Glyph } from "../icons";
import { CloseButton, CopyButton, td } from "../ui";
import LoraChain from "./LoraChain";
import NodeTable from "./NodeTable";

function Row({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  const kind = typeof value === "string" ? chainKind(label) : null;
  return (
    <tr>
      <td className={`${td} w-32 text-zinc-500`}>{label}</td>
      <td className={`${td} break-all`}>
        {kind && typeof value === "string" ? <ChainText text={value} kind={kind} /> : value}
      </td>
    </tr>
  );
}

function Settings({ d }: { d: ImageDetail }) {
  const f = d.file;
  return (
    <table className="w-full text-xs">
      <tbody>
        <Row label="path" value={f.rel_path} />
        <Row
          label="file"
          value={`${f.format.toUpperCase()} ${f.width ?? "?"}×${f.height ?? "?"}, ${fmtNum(f.megapixels)} MP, ${f.aspect_label ?? "?"}, ${fmtBytes(f.size)}`}
        />
        {settingsRows(d).map((row) => (
          <Row key={row.label} label={row.label} value={row.value} />
        ))}
      </tbody>
    </table>
  );
}

function Prompt({ label, text }: { label: string; text: string | null }) {
  if (text === null) return null;
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-500">{label}</span>
        <CopyButton label={`Copy ${label.toLowerCase()}`} text={text} />
      </div>
      <pre className="rounded bg-zinc-100 p-2 font-sans text-xs break-words whitespace-pre-wrap dark:bg-zinc-900">
        {text || "(empty)"}
      </pre>
    </div>
  );
}

/** Later stages' prompts, where they differ from the primary stage's shown above. */
function StagePrompts({ d }: { d: ImageDetail }) {
  const primary = d.generation;
  if (!primary) return null;
  return d.stages.slice(1).map((s) => (
    <Fragment key={s.index}>
      {s.positive_prompt !== primary.positive_prompt && (
        <Prompt label={`Stage ${s.index} positive prompt`} text={s.positive_prompt} />
      )}
      {s.negative_prompt !== primary.negative_prompt && (
        <Prompt label={`Stage ${s.index} negative prompt`} text={s.negative_prompt} />
      )}
    </Fragment>
  ));
}

function Details({ id }: { id: number }) {
  const queryClient = useQueryClient();
  const query = useImageDetail(id);
  const raw = () => queryClient.fetchQuery({ queryKey: ["raw", id], queryFn: () => api.raw(id) });
  const d = query.data;
  if (!d)
    return (
      <div className="p-4 text-zinc-500">{query.isError ? query.error.message : "Loading…"}</div>
    );
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-2">
        <CopyButton
          label="Copy prompt JSON"
          text={async () => JSON.stringify((await raw()).prompt, null, 2)}
        >
          Prompt JSON
        </CopyButton>
        <CopyButton
          label="Copy workflow JSON"
          text={async () => JSON.stringify((await raw()).workflow, null, 2)}
        >
          Workflow JSON
        </CopyButton>
        <a
          href={fileUrl(id)}
          download={d.file.rel_path.split("/").pop()}
          className="rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Download original
        </a>
      </div>
      <Settings d={d} />
      {d.generation && <LoraChain detail={d} />}
      {d.stages.length > 1 && (
        <div className="text-xs">
          <div className="font-semibold text-zinc-500">Sampler stages</div>
          {d.stages.map((s) => (
            <div key={s.index}>
              {s.index}. {s.model_family} on {s.base_model ?? "unknown model"}, {s.class_type} #
              {s.node_id}: {s.steps ?? "?"} steps, cfg {fmtNum(s.cfg)}, {s.sampler_name ?? "?"}/
              {s.scheduler ?? "?"}, denoise {fmtNum(s.denoise)}
            </div>
          ))}
        </div>
      )}
      {d.generation && (
        <>
          <Prompt label="Positive prompt" text={d.generation.positive_prompt} />
          <Prompt label="Negative prompt" text={d.generation.negative_prompt} />
        </>
      )}
      <StagePrompts d={d} />
      {d.input_images.length > 0 && (
        <div className="text-xs">
          <div className="font-semibold text-zinc-500">Input images</div>
          {d.input_images.map((i) => (
            <div key={i.node_id} className="break-all">
              node {i.node_id}: {i.filename ?? "?"}{" "}
              <span className="font-mono text-zinc-500">{i.sha256 ?? "no hash"}</span>
            </div>
          ))}
        </div>
      )}
      {d.warnings.length > 0 && (
        <div className="text-xs">
          <div className="font-semibold text-amber-600">Warnings</div>
          {d.warnings.map((w, i) => (
            <div key={i}>
              <span className="font-mono">{w.code}</span>
              {w.node_id && <span className="text-zinc-500"> node {w.node_id}</span>}
              {w.message && <span> — {w.message}</span>}
            </div>
          ))}
        </div>
      )}
      <NodeTable nodes={d.nodes} />
    </div>
  );
}

function ImagePane({ id }: { id: number }) {
  const [actualSize, setActualSize] = useState(false);
  const openMenu = useFileActions((s) => s.openMenu);
  return (
    <div
      className={`flex min-w-0 flex-1 bg-black ${actualSize ? "overflow-auto" : "items-center justify-center overflow-hidden"}`}
      onClick={() => setActualSize(!actualSize)}
      onContextMenu={(e) => {
        e.preventDefault();
        openMenu({ x: e.clientX, y: e.clientY, ids: [id] });
      }}
      title={actualSize ? "Click to fit" : "Click for 1:1"}
    >
      <img
        src={fileUrl(id)}
        alt=""
        className={
          actualSize
            ? "max-w-none cursor-zoom-out"
            : "max-h-full max-w-full cursor-zoom-in object-contain"
        }
      />
    </div>
  );
}

const KEY = "inline-flex rounded border border-zinc-300 px-0.5 py-px dark:border-zinc-700";

export default function DetailView() {
  const id = useUi((s) => s.detailId);
  const openDetail = useUi((s) => s.openDetail);
  const { order } = useImageOrder();

  useEffect(() => {
    if (id === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") openDetail(null);
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const index = order.indexOf(id);
      if (index < 0) return; // opened from an example outside the current order
      const next = order[index + (e.key === "ArrowRight" ? 1 : -1)];
      if (next !== undefined) {
        e.preventDefault();
        openDetail(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, order, openDetail]);

  if (id === null) return null;
  const index = order.indexOf(id);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-md"
      onClick={() => openDetail(null)}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="flex h-[90vh] w-[90vw] overflow-hidden rounded-lg bg-white shadow-2xl dark:bg-zinc-950"
        onClick={(e) => e.stopPropagation()}
      >
        <ImagePane key={id} id={id} />
        <div className="flex w-[460px] shrink-0 flex-col border-l border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
            <span className="font-medium">Image {id}</span>
            {index >= 0 && (
              <span className="flex items-center gap-1 text-xs text-zinc-500">
                {index + 1} of {order.length}
                <span className="ml-1 inline-flex gap-0.5" title="Step with the arrow keys">
                  <kbd className={KEY}>
                    <Glyph name="arrowLeft" label="Left arrow" className="size-3" />
                  </kbd>
                  <kbd className={KEY}>
                    <Glyph name="arrowRight" label="Right arrow" className="size-3" />
                  </kbd>
                </span>
              </span>
            )}
            <span className="flex-1" />
            <CloseButton onClick={() => openDetail(null)} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Details key={id} id={id} />
          </div>
        </div>
      </div>
    </div>
  );
}
