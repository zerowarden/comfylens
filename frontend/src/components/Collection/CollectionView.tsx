import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type DragEvent } from "react";

import { api, EXPORT_URL } from "../../api/client";
import type { PromptSummary } from "../../api/types";
import { draftFiles, emptySettings, imageFiles, importCollection } from "../../lib/collection";
import { fmtInt } from "../../lib/format";
import { useDebounced } from "../../lib/hooks";
import { useCollection } from "../../state/collection";
import { Glyph } from "../icons";
import { Button, FIELD, FamilyDot, LINK_BUTTON, Thumbnail } from "../ui";

const ACCEPT = "image/png,image/jpeg,image/webp";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function Card({ prompt }: { prompt: PromptSummary }) {
  const openPrompt = useCollection((s) => s.openPrompt);
  return (
    <button
      type="button"
      onClick={() => openPrompt(prompt.id)}
      className="flex flex-col overflow-hidden rounded border border-line text-left hover:border-accent"
    >
      <div className="flex aspect-square w-full items-center justify-center bg-subtle">
        <Thumbnail
          hash={prompt.cover_hash}
          fallback={
            <p className="line-clamp-6 p-3 text-xs text-muted">
              {prompt.positive || "No image or prompt text"}
            </p>
          }
        />
      </div>
      <div className="space-y-0.5 p-2">
        <div className="flex items-center gap-1.5">
          {prompt.model_family && (
            <FamilyDot family={prompt.model_family} title={prompt.model_family} />
          )}
          <span className="truncate font-medium" title={prompt.title}>
            {prompt.title}
          </span>
        </div>
        {prompt.tags.length > 0 && (
          <div className="truncate text-xs text-muted">{prompt.tags.join(" · ")}</div>
        )}
        {prompt.library_count !== null && prompt.library_count > 0 && (
          <div className="text-xs text-link">{fmtInt(prompt.library_count)} in library</div>
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
  const archiveInput = useRef<HTMLInputElement>(null);
  const client = useQueryClient();
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
        // A dropped export is imported; images become a new prompt.
        const files = [...e.dataTransfer.files];
        const archives = files.filter((f) => f.name.toLowerCase().endsWith(".zip"));
        for (const archive of archives) void importCollection(client, archive);
        const images = imageFiles(files);
        if (images.length > 0) void draftFiles(images);
      }}
    >
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line px-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search saved prompts"
          className={`w-64 px-2 py-0.5 ${FIELD}`}
        />
        {data && data.families.length > 0 && (
          <select
            value={family ?? ""}
            onChange={(e) => setFamily(e.target.value || null)}
            aria-label="Model family"
            className={`px-1 py-0.5 text-xs ${FIELD}`}
          >
            <option value="" className="bg-surface">
              All families
            </option>
            {data.families.map((f) => (
              <option key={f.value} value={f.value} className="bg-surface">
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
        <span className="h-5 border-l border-control" />
        <a
          href={EXPORT_URL}
          download
          title="Download every saved prompt and its images as one zip, as a backup or for another machine"
          className={LINK_BUTTON}
        >
          Export
        </a>
        <Button
          onClick={() => archiveInput.current?.click()}
          title="Add the prompts of an exported zip; prompts already here are skipped"
        >
          Import…
        </Button>
        <input
          ref={archiveInput}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void importCollection(client, file);
          }}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {list.isError && <div className="p-4 text-danger">{list.error.message}</div>}
        {data && data.items.length === 0 && (
          <div className="mx-auto max-w-md p-8 text-center text-muted">
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
        <div className="pointer-events-none absolute inset-2 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-accent/10 text-accent-text">
          Drop images to save them as a prompt, or an exported zip to import it
        </div>
      )}
    </div>
  );
}
