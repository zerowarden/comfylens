import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { api, originalUrl, thumbUrl } from "../../api/client";
import type { CollectionImage, SavedPrompt } from "../../api/types";
import {
  loraText,
  promptSettingsRows,
  refreshAfterCollectionWrite,
  showInLibrary,
} from "../../lib/collection";
import { fmtDateTime, fmtInt } from "../../lib/format";
import { useThumbnailFailure } from "../../lib/images";
import { useCollection } from "../../state/collection";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { Modal } from "../FileActions";
import { Glyph } from "../icons";
import { Button, CloseButton, CopyButton, PRIMARY, td } from "../ui";

const LINK =
  "rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-xs font-semibold text-zinc-500">{title}</div>
      {children}
    </div>
  );
}

function PromptText({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-500">{label}</span>
        <CopyButton label={`Copy ${label.toLowerCase()}`} text={text} />
      </div>
      <pre className="rounded bg-zinc-100 p-2 font-sans text-xs break-words whitespace-pre-wrap dark:bg-zinc-900">
        {text}
      </pre>
    </div>
  );
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
  const [failed, onThumbnailError] = useThumbnailFailure();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      title={title}
      className={`h-16 w-16 shrink-0 overflow-hidden rounded bg-zinc-100 disabled:cursor-default dark:bg-zinc-900 ${
        selected ? "outline-2 outline-sky-500" : ""
      }`}
    >
      {!failed && (
        <img
          src={thumbUrl(image.content_hash)}
          loading="lazy"
          alt=""
          onError={onThumbnailError}
          className="h-full w-full object-contain"
        />
      )}
    </button>
  );
}

function ImagePane({ prompt }: { prompt: SavedPrompt }) {
  const [index, setIndex] = useState(0);
  const [actualSize, setActualSize] = useState(false);
  const shown = prompt.references[Math.min(index, prompt.references.length - 1)];
  if (!shown) {
    return (
      <div className="flex min-w-0 flex-1 items-center justify-center bg-black p-8 text-zinc-400">
        No reference image
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-1 flex-col bg-black">
      <div
        className={`flex min-h-0 flex-1 ${actualSize ? "overflow-auto" : "items-center justify-center overflow-hidden"}`}
        onClick={() => setActualSize(!actualSize)}
        title={actualSize ? "Click to fit" : "Click for 1:1"}
      >
        <img
          key={shown.content_hash}
          src={originalUrl(shown.content_hash)}
          alt=""
          className={
            actualSize
              ? "max-w-none cursor-zoom-out"
              : "max-h-full max-w-full cursor-zoom-in object-contain"
          }
        />
      </div>
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
                className="absolute top-0.5 right-0.5 hidden rounded bg-black/60 p-0.5 text-white group-hover:block"
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
  return (
    <>
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
    </>
  );
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
      <p className="mb-4 text-xs text-zinc-500">
        The saved prompt and its copied reference images are removed from the collection. Library
        files are never touched.
      </p>
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <button
          type="button"
          autoFocus
          onClick={() => void remove()}
          className={`${PRIMARY} border-red-600 bg-red-600 hover:bg-red-700`}
        >
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
          <a href={`${originalUrl(first.content_hash)}?download=true`} className={LINK}>
            Download original
          </a>
        )}
        <Button onClick={() => setDeleting(true)} className="text-red-600 dark:text-red-400">
          Delete
        </Button>
      </div>
      {(prompt.tags.length > 0 || prompt.model_family || prompt.source_url) && (
        <div className="space-y-1 text-xs">
          {prompt.model_family && <div className="text-zinc-500">{prompt.model_family}</div>}
          {prompt.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {prompt.tags.map((t) => (
                <span key={t} className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
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
              className="block break-all text-sky-600 hover:underline dark:text-sky-400"
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
                <td className={`${td} w-32 text-zinc-500`}>{row.label}</td>
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
      <div className="text-xs text-zinc-500">
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
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 backdrop-blur-md"
      onClick={() => openPrompt(null)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={prompt?.title ?? "Saved prompt"}
        className="flex h-[90vh] w-[90vw] overflow-hidden rounded-lg bg-white shadow-2xl dark:bg-zinc-950"
        onClick={(e) => e.stopPropagation()}
      >
        {prompt ? (
          <ImagePane key={prompt.id} prompt={prompt} />
        ) : (
          <div className="flex-1 bg-black" />
        )}
        <div className="flex w-[460px] shrink-0 flex-col border-l border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
            <Glyph name="bookmark" className="size-4 text-sky-600" />
            <span className="min-w-0 flex-1 truncate font-medium">{prompt?.title ?? "…"}</span>
            <CloseButton onClick={() => openPrompt(null)} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {prompt ? (
              <Details prompt={prompt} />
            ) : (
              <div className="p-4 text-zinc-500">
                {query.isError ? query.error.message : "Loading…"}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
