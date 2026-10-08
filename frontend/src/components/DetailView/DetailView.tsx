import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, type ReactNode } from "react";

import { api, fileUrl } from "../../api/client";
import type { ImageDetail } from "../../api/types";
import { settingsRows } from "../../lib/compare";
import { saveImageToCollection } from "../../lib/collection";
import { baseName } from "../../lib/files";
import { fmtBytes, fmtNum, loadingText } from "../../lib/format";
import { useImageDetail, useImageOrder } from "../../lib/images";
import { useCollection } from "../../state/collection";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { chainKind } from "../../lib/chains";
import CollectionSection from "../Collection/CollectionSection";
import { ChainText, Glyph } from "../icons";
import { Button, Heading, LINK_BUTTON, td } from "../ui";
import {
  GraphCopyButtons,
  PromptBox,
  ViewerHeader,
  ViewerModal,
  ViewerSidebar,
  ZoomableImage,
} from "../Viewer";
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
        <Row label="tags" value={f.tags.join(", ")} />
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

/** Later stages' prompts, where they differ from the primary stage's shown above. */
function StagePrompts({ d }: { d: ImageDetail }) {
  const primary = d.generation;
  if (!primary) return null;
  return d.stages.slice(1).map((s) => (
    <Fragment key={s.index}>
      {s.positive_prompt !== primary.positive_prompt && (
        <PromptBox label={`Stage ${s.index} positive prompt`} text={s.positive_prompt} />
      )}
      {s.negative_prompt !== primary.negative_prompt && (
        <PromptBox label={`Stage ${s.index} negative prompt`} text={s.negative_prompt} />
      )}
    </Fragment>
  ));
}

/** The actions on the image, laid out as one section; the graph copies are secondary. */
function Actions({ id, relPath }: { id: number; relPath: string }) {
  const client = useQueryClient();
  const openDialog = useFileActions((s) => s.openDialog);
  const openLinking = useCollection((s) => s.openLinking);
  const raw = () => client.fetchQuery({ queryKey: ["raw", id], queryFn: () => api.raw(id) });
  return (
    <section className="space-y-2">
      <Heading>Actions</Heading>
      <div className="grid grid-cols-2 gap-1.5">
        <a
          href={fileUrl(id)}
          download={baseName(relPath)}
          className={`${LINK_BUTTON} inline-flex items-center justify-center gap-1.5 text-center`}
        >
          <Glyph name="download" className="size-3.5" />
          Download original
        </a>
        <Button
          className="inline-flex items-center justify-center gap-1.5"
          onClick={() => openDialog({ kind: "tags", ids: [id] })}
        >
          <Glyph name="tag" className="size-3.5" />
          Edit tags…
        </Button>
        <Button
          className="inline-flex items-center justify-center gap-1.5"
          onClick={() => void saveImageToCollection(id)}
        >
          <Glyph name="bookmarkPlus" className="size-3.5" />
          Save to collection
        </Button>
        <Button
          className="inline-flex items-center justify-center gap-1.5"
          onClick={() => openLinking([id])}
        >
          <Glyph name="link" className="size-3.5" />
          Add to saved prompt…
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
        Copy
        <GraphCopyButtons load={raw} />
      </div>
    </section>
  );
}

function Details({ id }: { id: number }) {
  const query = useImageDetail(id);
  const d = query.data;
  if (!d) return <div className="p-4 text-muted">{loadingText(query.error)}</div>;
  return (
    <div className="space-y-3 p-3">
      <Actions id={id} relPath={d.file.rel_path} />
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
          <PromptBox label="Positive prompt" text={d.generation.positive_prompt} />
          <PromptBox label="Negative prompt" text={d.generation.negative_prompt} />
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

/** Matches the fade-out in index.css: the closed view unmounts once that animation has run. */
const FADE_OUT_MS = 150;

export default function DetailView() {
  const id = useUi((s) => s.detailId);
  const last = useUi((s) => s.lastDetailId);
  const openDetail = useUi((s) => s.openDetail);
  const dropDetail = useUi((s) => s.dropDetail);
  const { order } = useImageOrder();
  // The image on screen: the open one, or the last one while its view fades out.
  const shown = id ?? last;

  // Hold the closed view on screen for its fade-out, then unmount it.
  useEffect(() => {
    if (id !== null || last === null) return;
    const timer = window.setTimeout(dropDetail, FADE_OUT_MS);
    return () => window.clearTimeout(timer);
  }, [id, last, dropDetail]);

  // -1 when opened from an example outside the current order: no stepping then.
  const index = shown === null ? -1 : order.indexOf(shown);
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

  if (shown === null) return null;
  return (
    <ViewerModal
      layer="z-50"
      onClose={() => openDetail(null)}
      className={id === null ? "animate-fade-out" : "animate-fade-in"}
    >
      <ImagePane key={shown} id={shown} />
      <ViewerSidebar
        header={
          <ViewerHeader onClose={() => openDetail(null)}>
            <span className="font-medium">Image {shown}</span>
            {index >= 0 && (
              <span className="text-xs text-muted">
                {index + 1} of {order.length}
              </span>
            )}
            <span className="flex-1" />
          </ViewerHeader>
        }
      >
        <Details key={shown} id={shown} />
      </ViewerSidebar>
    </ViewerModal>
  );
}
