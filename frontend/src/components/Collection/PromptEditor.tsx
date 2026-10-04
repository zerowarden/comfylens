import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
  type SubmitEvent,
} from "react";

import { api, thumbUrl } from "../../api/client";
import type { CollectionImage, Draft, PromptInput } from "../../api/types";
import {
  appendReferences,
  fillEmptyFields,
  imageFiles,
  inputOf,
  inputOfDraft,
  loraText,
  parseTags,
  promptSettingsRows,
  refreshAfterCollectionWrite,
  type DraftFields,
} from "../../lib/collection";
import { useCollection, type Editor } from "../../state/collection";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { Modal } from "../FileActions";
import { Glyph } from "../icons";
import { Button, PRIMARY } from "../ui";

const FIELD =
  "mt-1 block w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm text-zinc-900 outline-none focus:border-sky-500 dark:border-zinc-700 dark:text-zinc-100";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-zinc-500">
      {label}
      {children}
    </label>
  );
}

const ACCEPT = "image/png,image/jpeg,image/webp";

/** The reference images, plus a target for pasting, dropping or picking more. */
function ImagesField({
  images,
  adding,
  dragging,
  note,
  onRemove,
  onPick,
}: {
  images: CollectionImage[];
  adding: number;
  dragging: boolean;
  /** Shown in place of the hint, so the field keeps its height. */
  note: string | null;
  onRemove: (hash: string) => void;
  onPick: () => void;
}) {
  const ring = dragging ? "border-sky-500 bg-sky-500/10" : "border-zinc-300 dark:border-zinc-700";
  return (
    <div className={`rounded border border-dashed p-2 ${ring}`}>
      {/* The add tile comes first: new images appear after it and nothing moves. */}
      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          onClick={onPick}
          title="Add reference images"
          className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded border border-zinc-300 text-xs text-zinc-500 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          <Glyph name="imagePlus" className="size-5" />
          Add image
        </button>
        {images.map((image) => (
          <div key={image.content_hash} className="group relative">
            <img
              src={thumbUrl(image.content_hash)}
              alt=""
              className="h-20 w-20 rounded bg-zinc-100 object-contain dark:bg-zinc-800"
            />
            <button
              type="button"
              title="Remove this reference image"
              aria-label="Remove this reference image"
              onClick={() => onRemove(image.content_hash)}
              className="absolute top-0.5 right-0.5 rounded bg-black/60 p-0.5 text-white opacity-0 group-hover:opacity-100 focus:opacity-100"
            >
              <Glyph name="x" className="size-3" />
            </button>
          </div>
        ))}
        {Array.from({ length: adding }, (_, i) => (
          <div
            key={`adding-${i}`}
            className="flex h-20 w-20 animate-pulse items-center justify-center rounded bg-zinc-100 text-xs text-zinc-500 dark:bg-zinc-800"
          >
            Adding…
          </div>
        ))}
      </div>
      {/* One line either way: a wrapped note would push the fields below it down. */}
      {note ? (
        <p className="mt-1 truncate text-xs text-amber-700 dark:text-amber-400" title={note}>
          {note}
        </p>
      ) : (
        <p className="mt-1 truncate text-xs text-zinc-500">
          Paste an image (Ctrl+V), drop files here, or click Add image. PNG, JPEG or WebP.
        </p>
      )}
    </div>
  );
}

function EditorForm({ editor }: { editor: Editor }) {
  const client = useQueryClient();
  const openEditor = useCollection((s) => s.openEditor);
  const openPrompt = useCollection((s) => s.openPrompt);
  const notify = useFileActions((s) => s.notify);
  const initial: PromptInput =
    editor.mode === "new" ? inputOfDraft(editor.draft, editor.references) : inputOf(editor.prompt);
  const [fields, setFields] = useState<DraftFields>({
    title: initial.title,
    positive: initial.positive,
    negative: initial.negative,
    family: initial.model_family ?? "",
    settings: initial.settings,
  });
  const set = (change: Partial<DraftFields>) => setFields((f) => ({ ...f, ...change }));
  const { title, positive, negative, family } = fields;
  const [notes, setNotes] = useState(initial.notes);
  const [sourceUrl, setSourceUrl] = useState(initial.source_url ?? "");
  const [tags, setTags] = useState(initial.tags.join(", "));
  const [references, setReferences] = useState<CollectionImage[]>(
    editor.mode === "new" ? editor.references : editor.prompt.references,
  );
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(
    editor.mode === "new" && editor.draft.metadata === "none" && editor.references.length > 0
      ? "No generation metadata was found in this image. Images pasted from the clipboard lose it; drop or pick the file itself to keep it."
      : null,
  );
  const [adding, setAdding] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const facets = useQuery({
    queryKey: ["collection", "list", "", null, null],
    queryFn: () => api.collection({}),
  });

  const close = () => openEditor(null);
  const settings = promptSettingsRows(fields.settings);
  const loras = fields.settings.loras.map(loraText);

  /** Upload files one at a time; each becomes a reference as soon as it is stored. */
  const addFiles = async (files: File[], pasted: boolean) => {
    if (files.length === 0) return;
    setAdding((n) => n + files.length);
    setError(null);
    const drafts: Draft[] = [];
    const failures: string[] = [];
    for (const file of files) {
      try {
        const draft = await api.draftFromFile(file);
        drafts.push(draft);
        setReferences((current) => appendReferences(current, [draft]));
      } catch (err) {
        failures.push(`${file.name || "pasted image"}: ${(err as Error).message}`);
      } finally {
        setAdding((n) => n - 1);
      }
    }
    setFields((f) => fillEmptyFields(f, drafts));
    if (failures.length > 0) setError(failures.join("; "));
    if (pasted && drafts.some((d) => d.metadata === "none")) {
      setNote(
        "Pasted images carry no generation metadata. If the original file has some, drop or pick the file instead.",
      );
    }
  };
  const onWindowFiles = useEffectEvent((files: File[], pasted: boolean) => {
    void addFiles(files, pasted);
  });

  // While the editor is open, pasted and dropped images become references wherever they land.
  // A text paste carries no files and goes to the focused field as usual.
  useEffect(() => {
    const hasFiles = (e: DragEvent) => e.dataTransfer?.types.includes("Files") ?? false;
    const onPaste = (e: ClipboardEvent) => {
      const files = imageFiles(e.clipboardData?.files ?? []);
      if (files.length === 0) return;
      e.preventDefault();
      onWindowFiles(files, true);
    };
    const onDragOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (e.relatedTarget === null) setDragging(false); // left the window
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setDragging(false);
      onWindowFiles(imageFiles(e.dataTransfer?.files ?? []), false);
    };
    window.addEventListener("paste", onPaste);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  const submit = async (e: SubmitEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("A title is required.");
      return;
    }
    const body: PromptInput = {
      ...initial,
      title: title.trim(),
      positive,
      negative,
      notes,
      source_url: sourceUrl.trim() || null,
      model_family: family.trim() || null,
      settings: fields.settings,
      tags: parseTags(tags),
      references: references.map((r) => r.content_hash),
    };
    if (adding > 0) {
      setError("Wait for the images to finish uploading.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved =
        editor.mode === "new"
          ? await api.createPrompt(body)
          : await api.updatePrompt(editor.prompt.id, body);
      client.setQueryData(["collection", "prompt", saved.id], saved);
      close();
      refreshAfterCollectionWrite(client);
      if (useUi.getState().view === "collection") openPrompt(saved.id);
      else notify({ text: `Saved “${saved.title}” to the collection`, tone: "info" });
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <Modal
      title={editor.mode === "new" ? "Save to collection" : "Edit saved prompt"}
      onClose={close}
      width="w-[720px]"
      align="top"
    >
      <form onSubmit={(e) => void submit(e)} className="space-y-3">
        <ImagesField
          images={references}
          adding={adding}
          dragging={dragging}
          note={note}
          onRemove={(hash) => setReferences(references.filter((r) => r.content_hash !== hash))}
          onPick={() => fileInput.current?.click()}
        />
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = "";
            void addFiles(files, false);
          }}
        />
        <Field label="Title">
          <input
            value={title}
            onChange={(e) => set({ title: e.target.value })}
            maxLength={200}
            autoFocus
            className={FIELD}
          />
        </Field>
        <Field label="Positive prompt">
          <textarea
            value={positive}
            onChange={(e) => set({ positive: e.target.value })}
            rows={6}
            className={`${FIELD} font-mono text-xs`}
          />
        </Field>
        <Field label="Negative prompt">
          <textarea
            value={negative}
            onChange={(e) => set({ negative: e.target.value })}
            rows={2}
            className={`${FIELD} font-mono text-xs`}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tags, comma separated">
            <input value={tags} onChange={(e) => setTags(e.target.value)} className={FIELD} />
          </Field>
          <Field label="Model family">
            <input
              value={family}
              onChange={(e) => set({ family: e.target.value })}
              list="collection-families"
              className={FIELD}
            />
            <datalist id="collection-families">
              {facets.data?.families.map((f) => (
                <option key={f.value} value={f.value} />
              ))}
            </datalist>
          </Field>
        </div>
        <Field label="Source URL">
          <input
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="Where you found it"
            className={FIELD}
          />
        </Field>
        <Field label="Notes">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={FIELD}
          />
        </Field>
        {(settings.length > 0 || loras.length > 0) && (
          <p className="text-xs text-zinc-500">
            Settings from the image:{" "}
            {[...settings.map((r) => `${r.label} ${r.value}`), ...loras].join(" · ")}
          </p>
        )}
        {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={close}>Cancel</Button>
          <button
            type="submit"
            disabled={saving || adding > 0}
            className={`${PRIMARY} border-sky-600 bg-sky-600 hover:bg-sky-700`}
          >
            {editor.mode === "new" ? "Save" : "Save changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Creates a saved prompt from a draft, or edits one. */
export default function PromptEditor() {
  const editor = useCollection((s) => s.editor);
  if (!editor) return null;
  return <EditorForm editor={editor} />;
}
