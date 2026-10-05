import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { api, originalUrl } from "../../api/client";
import type { CollectionImage, SavedPrompt } from "../../api/types";
import {
  loraText,
  promptSettingsRows,
  refreshAfterCollectionWrite,
  showInLibrary,
} from "../../lib/collection";
import { fmtDateTime, fmtInt, loadingText } from "../../lib/format";
import { useCollection } from "../../state/collection";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { Glyph } from "../icons";
import { Button, DESTRUCTIVE, Heading, LINK_BUTTON, Thumbnail, td } from "../ui";
import {
  GraphCopyButtons,
  Modal,
  PromptBox,
  ViewerHeader,
  ViewerModal,
  ViewerSidebar,
  ZoomableImage,
} from "../Modals";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <Heading>{title}</Heading>
      {children}
    </div>
  );
}

function PromptText({ label, text }: { label: string; text: string }) {
  return text ? <PromptBox label={label} text={text} /> : null;
}

function Thumb({
  image,
  selected = false,
  onClick,
  title,
}: {
  image: CollectionImage;
  selected?: boolean;
  onClick?: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      title={title}
      className={`h-16 w-16 shrink-0 overflow-hidden rounded bg-subtle disabled:cursor-default ${
        selected ? "outline-2 outline-accent" : ""
      }`}
    >
      <Thumbnail hash={image.content_hash} />
    </button>
  );
}

function ImagePane({ prompt }: { prompt: SavedPrompt }) {
  const [index, setIndex] = useState(0);
  const shown = prompt.references[Math.min(index, prompt.references.length - 1)];
  if (!shown) {
    return (
      <div className="flex min-w-0 flex-1 items-center justify-center bg-stage p-8 text-on-stage">
        No reference image
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-1 flex-col bg-stage">
      <ZoomableImage src={originalUrl(shown.content_hash)} className="min-h-0 flex-1" />
      {prompt.references.length > 1 && (
        <div className="flex shrink-0 gap-1 overflow-x-auto p-2">
          {prompt.references.map((r, i) => (
            <Thumb
              key={r.content_hash}
              image={r}
              selected={r === shown}
              onClick={() => setIndex(i)}
              title={`Reference ${i + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Attempts({ prompt }: { prompt: SavedPrompt }) {
  const client = useQueryClient();
  const openDetail = useUi((s) => s.openDetail);
  const notify = useFileActions((s) => s.notify);
  if (prompt.attempts.length === 0) return null;
  const unlink = async (hash: string) => {
    try {
      const updated = await api.unlinkAttempts(prompt.id, [hash]);
      client.setQueryData(["collection", "prompt", prompt.id], updated);
    } catch (e) {
      notify({ text: `Could not unlink the image: ${(e as Error).message}`, tone: "error" });
    }
    refreshAfterCollectionWrite(client);
  };
  return (
    <Section title={`Attempts (${fmtInt(prompt.attempts.length)})`}>
      <div className="flex flex-wrap gap-1">
        {prompt.attempts.map((a) => {
          const id = a.library_ids[0];
          return (
            <div key={a.content_hash} className="group relative">
              <Thumb
                image={a}
                onClick={id === undefined ? undefined : () => openDetail(id)}
                title={id === undefined ? "Not in this library" : `Open image ${id}`}
              />
              <button
                type="button"
                title="Unlink this image"
                aria-label="Unlink this image"
                onClick={() => void unlink(a.content_hash)}
                className="absolute top-0.5 right-0.5 hidden rounded bg-overlay/60 p-0.5 text-on-overlay group-hover:block"
              >
                <Glyph name="x" className="size-3" />
              </button>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function RawCopy({ hash }: { hash: string }) {
  const client = useQueryClient();
  const raw = () =>
    client.fetchQuery({
      queryKey: ["collection", "raw", hash],
      queryFn: () => api.originalRaw(hash),
      staleTime: Infinity,
    });
  return <GraphCopyButtons load={raw} />;
}

function DeleteDialog({ prompt, onClose }: { prompt: SavedPrompt; onClose: () => void }) {
  const client = useQueryClient();
  const notify = useFileActions((s) => s.notify);
  const openPrompt = useCollection((s) => s.openPrompt);
  const remove = async () => {
    onClose();
    try {
      await api.deletePrompt(prompt.id);
      openPrompt(null);
      notify({ text: `Deleted “${prompt.title}”`, tone: "info" });
    } catch (e) {
      notify({ text: `Could not delete: ${(e as Error).message}`, tone: "error" });
    }
    refreshAfterCollectionWrite(client);
  };
  return (
    <Modal title={`Delete “${prompt.title}”?`} onClose={onClose}>
      <p className="mb-4 text-xs text-muted">
        The saved prompt and its copied reference images are removed from the collection. Library
        files are never touched.
      </p>
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <button type="button" autoFocus onClick={() => void remove()} className={DESTRUCTIVE}>
          Delete
        </button>
      </div>
    </Modal>
  );
}

function Details({ prompt }: { prompt: SavedPrompt }) {
  const openEditor = useCollection((s) => s.openEditor);
  const [deleting, setDeleting] = useState(false);
  const first = prompt.references[0];
  // A prompt can mix images found online with ComfyUI outputs: copy from one that has a graph.
  const withWorkflow = prompt.references.find((r) => r.has_workflow);
  const settings = promptSettingsRows(prompt.settings);
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => showInLibrary(prompt.id)}
          title="Show the library images of this prompt"
        >
          Show in library
          {prompt.library_count !== null && ` (${fmtInt(prompt.library_count)})`}
        </Button>
        <Button onClick={() => openEditor({ mode: "edit", prompt })}>Edit</Button>
        {withWorkflow && <RawCopy hash={withWorkflow.content_hash} />}
        {first && (
          <a href={`${originalUrl(first.content_hash)}?download=true`} className={LINK_BUTTON}>
            Download original
          </a>
        )}
        <Button onClick={() => setDeleting(true)} className="text-danger">
          Delete
        </Button>
      </div>
      {(prompt.tags.length > 0 || prompt.model_family || prompt.source_url) && (
        <div className="space-y-1 text-xs">
          {prompt.model_family && <div className="text-muted">{prompt.model_family}</div>}
          {prompt.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {prompt.tags.map((t) => (
                <span key={t} className="rounded bg-subtle px-1.5 py-0.5">
                  {t}
                </span>
              ))}
            </div>
          )}
          {prompt.source_url && (
            <a
              href={prompt.source_url}
              target="_blank"
              rel="noreferrer"
              className="block break-all text-link hover:underline"
            >
              {prompt.source_url}
            </a>
          )}
        </div>
      )}
      <PromptText label="Positive prompt" text={prompt.positive} />
      <PromptText label="Negative prompt" text={prompt.negative} />
      {settings.length > 0 && (
        <table className="w-full text-xs">
          <tbody>
            {settings.map((row) => (
              <tr key={row.label}>
                <td className={`${td} w-32 text-muted`}>{row.label}</td>
                <td className={`${td} break-all`}>{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {prompt.settings.loras.length > 0 && (
        <Section title="LoRAs">
          <ul className="text-xs">
            {prompt.settings.loras.map((l, i) => (
              <li key={i}>{loraText(l)}</li>
            ))}
          </ul>
        </Section>
      )}
      {prompt.notes && (
        <Section title="Notes">
          <p className="text-xs whitespace-pre-wrap">{prompt.notes}</p>
        </Section>
      )}
      <Attempts prompt={prompt} />
      <div className="text-xs text-muted">
        Saved {fmtDateTime(prompt.created_at)}
        {prompt.updated_at !== prompt.created_at && `, changed ${fmtDateTime(prompt.updated_at)}`}
      </div>
      {deleting && <DeleteDialog prompt={prompt} onClose={() => setDeleting(false)} />}
    </div>
  );
}

/** A saved prompt in a modal, sized like the library's detail view, which opens above it. */
export default function PromptDetail() {
  const id = useCollection((s) => s.openId);
  const openPrompt = useCollection((s) => s.openPrompt);
  const query = useQuery({
    queryKey: ["collection", "prompt", id],
    queryFn: () => api.savedPrompt(id!),
    enabled: id !== null,
  });

  useEffect(() => {
    if (id === null) return;
    const onKey = (e: KeyboardEvent) => {
      // The library detail view, the editor and dialogs above this one take Escape first.
      const covered =
        useUi.getState().detailId !== null ||
        useCollection.getState().editor !== null ||
        useCollection.getState().linking !== null;
      if (e.key === "Escape" && !covered) openPrompt(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, openPrompt]);

  if (id === null) return null;
  const prompt = query.data;
  return (
    <ViewerModal
      layer="z-40"
      label={prompt?.title ?? "Saved prompt"}
      onClose={() => openPrompt(null)}
    >
      {prompt ? <ImagePane key={prompt.id} prompt={prompt} /> : <div className="flex-1 bg-stage" />}
      <ViewerSidebar
        header={
          <ViewerHeader onClose={() => openPrompt(null)}>
            <Glyph name="bookmark" className="size-4 text-link" />
            <span className="min-w-0 flex-1 truncate font-medium">{prompt?.title ?? "…"}</span>
          </ViewerHeader>
        }
      >
        {prompt ? (
          <Details prompt={prompt} />
        ) : (
          <div className="p-4 text-muted">{loadingText(query.error)}</div>
        )}
      </ViewerSidebar>
    </ViewerModal>
  );
}
