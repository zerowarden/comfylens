import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type DragEvent } from "react";

import { api, thumbUrl } from "../../api/client";
import type { PromptSummary } from "../../api/types";
import { familyColor } from "../../lib/colors";
import { draftFiles, emptySettings } from "../../lib/collection";
import { fmtInt } from "../../lib/format";
import { useDebounced } from "../../lib/hooks";
import { useThumbnailFailure } from "../../lib/images";
import { useCollection } from "../../state/collection";
import { Glyph } from "../icons";
import { Button } from "../ui";

const ACCEPT = "image/png,image/jpeg,image/webp";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function Card({ prompt }: { prompt: PromptSummary }) {
  const openPrompt = useCollection((s) => s.openPrompt);
  const [failed, onThumbnailError] = useThumbnailFailure();
  return (
    <button
      type="button"
      onClick={() => openPrompt(prompt.id)}
      className="flex flex-col overflow-hidden rounded border border-zinc-200 text-left hover:border-sky-500 dark:border-zinc-800"
    >
      <div className="flex aspect-square w-full items-center justify-center bg-zinc-100 dark:bg-zinc-900">
        {prompt.cover_hash && !failed ? (
          <img
            src={thumbUrl(prompt.cover_hash)}
            loading="lazy"
            decoding="async"
            alt=""
            onError={onThumbnailError}
            className="h-full w-full object-contain"
          />
        ) : (
          <p className="line-clamp-6 p-3 text-xs text-zinc-500">
            {prompt.positive || "No image or prompt text"}
          </p>
        )}
      </div>
      <div className="space-y-0.5 p-2">
        <div className="flex items-center gap-1.5">
          {prompt.model_family && (
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: familyColor(prompt.model_family) }}
              title={prompt.model_family}
            />
          )}
          <span className="truncate font-medium" title={prompt.title}>
            {prompt.title}
          </span>
        </div>
        {prompt.tags.length > 0 && (
          <div className="truncate text-xs text-zinc-500">{prompt.tags.join(" · ")}</div>
        )}
        {prompt.library_count !== null && prompt.library_count > 0 && (
          <div className="text-xs text-sky-700 dark:text-sky-400">
            {fmtInt(prompt.library_count)} in library
          </div>
        )}
      </div>
    </button>
  );
}

export default function CollectionView() {
  const [text, setText] = useState("");
  const q = useDebounced(text, 300);
  const [tag, setTag] = useState<string | null>(null);
  const [family, setFamily] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const openEditor = useCollection((s) => s.openEditor);
  const list = useQuery({
    queryKey: ["collection", "list", q, tag, family],
    queryFn: () => api.collection({ q, tag, family }),
    placeholderData: keepPreviousData,
  });

  // Paste an image anywhere in the view, except into a text field or over an open dialog.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const { editor, linking } = useCollection.getState();
      if (isTyping(e.target) || editor || linking) return;
      const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith("image/"));
      if (files.length === 0) return;
      e.preventDefault();
      void draftFiles(files);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  const hasFiles = (e: DragEvent) => e.dataTransfer.types.includes("Files");
  const data = list.data;
  const filtered = text.trim() !== "" || tag !== null || family !== null;
  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col"
      onDragOver={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragging(false);
        void draftFiles([...e.dataTransfer.files]);
      }}
    >
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-zinc-200 px-3 dark:border-zinc-800">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search saved prompts"
          className="w-64 rounded border border-zinc-300 bg-transparent px-2 py-0.5 dark:border-zinc-700"
        />
        {data && data.families.length > 0 && (
          <select
            value={family ?? ""}
            onChange={(e) => setFamily(e.target.value || null)}
            aria-label="Model family"
            className="rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-xs dark:border-zinc-700"
          >
            <option value="" className="bg-white dark:bg-zinc-900">
              All families
            </option>
            {data.families.map((f) => (
              <option key={f.value} value={f.value} className="bg-white dark:bg-zinc-900">
                {f.value} ({fmtInt(f.count)})
              </option>
            ))}
          </select>
        )}
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
          {data?.tags.map((t) => (
            <Button
              key={t.value}
              active={tag === t.value}
              onClick={() => setTag(tag === t.value ? null : t.value)}
            >
              {t.value}
            </Button>
          ))}
        </div>
        <Button
          onClick={() =>
            openEditor({
              mode: "new",
              references: [],
              draft: {
                original: null,
                title: "",
                positive: "",
                negative: "",
                model_family: null,
                settings: emptySettings(),
                metadata: "none",
              },
            })
          }
        >
          New prompt
        </Button>
        <Button
          className="inline-flex items-center gap-1"
          onClick={() => fileInput.current?.click()}
          title="Add images from your computer; you can also drop or paste them here"
        >
          <Glyph name="imagePlus" className="size-3.5" /> Add images
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = "";
            if (files.length > 0) void draftFiles(files);
          }}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {list.isError && <div className="p-4 text-red-600">{list.error.message}</div>}
        {data && data.items.length === 0 && (
          <div className="mx-auto max-w-md p-8 text-center text-zinc-500">
            {filtered ? (
              "No saved prompts match."
            ) : (
              <>
                <p className="mb-2 font-medium">No saved prompts yet.</p>
                <p>
                  Drop or paste images here, click New prompt, or right-click an image in the
                  library and choose Save to collection.
                </p>
              </>
            )}
          </div>
        )}
        {data && data.items.length > 0 && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
            {data.items.map((p) => (
              <Card key={p.id} prompt={p} />
            ))}
          </div>
        )}
      </div>
      {dragging && (
        <div className="pointer-events-none absolute inset-2 flex items-center justify-center rounded-lg border-2 border-dashed border-sky-500 bg-sky-500/10 text-sky-700 dark:text-sky-300">
          Drop images to save them as a prompt
        </div>
      )}
    </div>
  );
}
