import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, type ReactNode } from "react";

import { api, fileUrl } from "../../api/client";
import type { ImageDetail } from "../../api/types";
import { settingsRows } from "../../lib/compare";
import { fmtBytes, fmtNum, loadingText } from "../../lib/format";
import { useImageDetail, useImageOrder } from "../../lib/images";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { chainKind } from "../../lib/chains";
import CollectionSection from "../Collection/CollectionSection";
import { ChainText, Glyph } from "../icons";
import { Button, LINK_BUTTON, td } from "../ui";
import {
  GraphCopyButtons,
  PromptBox,
  ViewerHeader,
  ViewerModal,
  ViewerSidebar,
  ZoomableImage,
} from "../Modals";
import LoraChain from "./LoraChain";
import NodeTable from "./NodeTable";

function Row({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  const kind = typeof value === "string" ? chainKind(label) : null;
  return (
    <tr>
      <td className={`${td} w-32 text-muted`}>{label}</td>
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
  return text === null ? null : <PromptBox label={label} text={text} />;
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
  if (!d) return <div className="p-4 text-muted">{loadingText(query.error)}</div>;
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-2">
        <GraphCopyButtons load={raw} />
        <a href={fileUrl(id)} download={d.file.rel_path.split("/").pop()} className={LINK_BUTTON}>
          Download original
        </a>
      </div>
      <CollectionSection id={id} />
      <Settings d={d} />
      {d.generation && <LoraChain detail={d} />}
      {d.stages.length > 1 && (
        <div className="text-xs">
          <div className="font-semibold text-muted">Sampler stages</div>
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
          <div className="font-semibold text-muted">Input images</div>
          {d.input_images.map((i) => (
            <div key={i.node_id} className="break-all">
              node {i.node_id}: {i.filename ?? "?"}{" "}
              <span className="font-mono text-muted">{i.sha256 ?? "no hash"}</span>
            </div>
          ))}
        </div>
      )}
      {d.warnings.length > 0 && (
        <div className="text-xs">
          <div className="font-semibold text-warning">Warnings</div>
          {d.warnings.map((w, i) => (
            <div key={i}>
              <span className="font-mono">{w.code}</span>
              {w.node_id && <span className="text-muted"> node {w.node_id}</span>}
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
  const openMenu = useFileActions((s) => s.openMenu);
  return (
    <ZoomableImage
      src={fileUrl(id)}
      className="min-w-0 flex-1 bg-stage"
      onContextMenu={(e) => {
        e.preventDefault();
        openMenu({ x: e.clientX, y: e.clientY, ids: [id] });
      }}
    />
  );
}

export default function DetailView() {
  const id = useUi((s) => s.detailId);
  const openDetail = useUi((s) => s.openDetail);
  const { order } = useImageOrder();

  // -1 when opened from an example outside the current order: no stepping then.
  const index = id === null ? -1 : order.indexOf(id);
  const previous = index >= 0 ? order[index - 1] : undefined;
  const next = index >= 0 ? order[index + 1] : undefined;

  useEffect(() => {
    if (id === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") openDetail(null);
      const target = e.key === "ArrowLeft" ? previous : e.key === "ArrowRight" ? next : undefined;
      if (target !== undefined) {
        e.preventDefault();
        openDetail(target);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, previous, next, openDetail]);

  if (id === null) return null;
  return (
    <ViewerModal layer="z-50" onClose={() => openDetail(null)}>
      <ImagePane key={id} id={id} />
      <ViewerSidebar
        header={
          <ViewerHeader onClose={() => openDetail(null)}>
            <span className="font-medium">Image {id}</span>
            {index >= 0 && (
              <span className="flex items-center gap-1 text-xs text-muted">
                {index + 1} of {order.length}
                <span className="ml-1 inline-flex gap-0.5">
                  <Button
                    ghost
                    title="Previous image (Left arrow)"
                    ariaLabel="Previous image"
                    disabled={previous === undefined}
                    onClick={() => previous !== undefined && openDetail(previous)}
                    className="px-0.5"
                  >
                    <Glyph name="arrowLeft" className="size-3.5" />
                  </Button>
                  <Button
                    ghost
                    title="Next image (Right arrow)"
                    ariaLabel="Next image"
                    disabled={next === undefined}
                    onClick={() => next !== undefined && openDetail(next)}
                    className="px-0.5"
                  >
                    <Glyph name="arrowRight" className="size-3.5" />
                  </Button>
                </span>
              </span>
            )}
            <span className="flex-1" />
          </ViewerHeader>
        }
      >
        <Details key={id} id={id} />
      </ViewerSidebar>
    </ViewerModal>
  );
}
