import { useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
  type SubmitEvent,
} from "react";

import { api } from "../../api/client";
import type { CollectionImage, PromptInput } from "../../api/types";
import { refreshAfterCollectionWrite, uploadDrafts, useCollectionList } from "../../lib/collection";
import {
  appendReferences,
  fillEmptyFields,
  imageFiles,
  inputOf,
  inputOfDraft,
  parseTags,
  type DraftFields,
} from "../../lib/draft";
import { IMAGE_ACCEPT, hasFiles } from "../../lib/dom";
import { errorText } from "../../lib/format";
import { loraText, promptSettingsRows } from "../../lib/settings";
import { useCollection, type Editor } from "../../state/collection";
import { useFileActions } from "../../state/fileActions";
import { useUi } from "../../state/ui";
import { Modal } from "../Modal";
import { Glyph } from "../icons";
import { Button, DialogActions, FOCUS_FIELD, PRIMARY, Thumbnail } from "../ui";

const FIELD = `mt-1 block w-full px-2 py-1 text-sm ${FOCUS_FIELD}`;

const PASTED_NO_METADATA =
  "Pasted images carry no generation metadata. If the original file has some, drop or pick the file instead.";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-muted">
      {label}
      {children}
    </label>
  );
}

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
  const ring = dragging ? "border-accent bg-accent/10" : "border-control";
  return (
    <div className={`rounded border border-dashed p-2 ${ring}`}>
      {/* The add tile comes first: new images appear after it and nothing moves. */}
      <div className="flex flex-wrap gap-1">
        <button
          type="button"
          onClick={onPick}
          title="Add reference images"
          className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded border border-control text-xs text-muted hover:bg-hover"
        >
          <Glyph name="imagePlus" className="size-5" />
          Add image
        </button>
        {images.map((image) => (
          <div key={image.content_hash} className="group relative">
            <div className="h-20 w-20 overflow-hidden rounded bg-subtle">
              <Thumbnail hash={image.content_hash} />
            </div>
            <button
              type="button"
              title="Remove this reference image"
              aria-label="Remove this reference image"
              onClick={() => onRemove(image.content_hash)}
              className="absolute top-0.5 right-0.5 rounded bg-overlay/60 p-0.5 text-on-overlay opacity-0 group-hover:opacity-100 focus:opacity-100"
            >
              <Glyph name="x" className="size-3" />
            </button>
          </div>
        ))}
        {Array.from({ length: adding }, (_, i) => (
          <div
            key={`adding-${i}`}
            className="flex h-20 w-20 animate-pulse items-center justify-center rounded bg-subtle text-xs text-muted"
          >
            Adding…
          </div>
        ))}
      </div>
      {/* One line either way: a wrapped note would push the fields below it down. */}
      {note ? (
        <p className="mt-1 truncate text-xs text-warning" title={note}>
          {note}
        </p>
      ) : (
        <p className="mt-1 truncate text-xs text-muted">
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
      ? PASTED_NO_METADATA
      : null,
  );
  const [adding, setAdding] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const facets = useCollectionList();

  const close = () => openEditor(null);
  const settings = promptSettingsRows(fields.settings);
  const loras = fields.settings.loras.map(loraText);

  /** Upload files one at a time; each becomes a reference as soon as it is stored. */
  const addFiles = async (files: File[], pasted: boolean) => {
    if (files.length === 0) return;
    setAdding((n) => n + files.length);
    setError(null);
    const { drafts, failures } = await uploadDrafts(files, {
      onDraft: (draft) => setReferences((current) => appendReferences(current, [draft])),
      onFile: () => setAdding((n) => n - 1),
    });
    setFields((f) => fillEmptyFields(f, drafts));
    if (failures.length > 0) setError(failures.join("; "));
    if (pasted && drafts.some((d) => d.metadata === "none")) setNote(PASTED_NO_METADATA);
  };
  const onWindowFiles = useEffectEvent((files: File[], pasted: boolean) => {
    void addFiles(files, pasted);
  });

  // While the editor is open, pasted and dropped images become references wherever they land.
  // A text paste carries no files and goes to the focused field as usual.
  useEffect(() => {
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
    } catch (e) {
      setError(errorText(e));
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
          accept={IMAGE_ACCEPT}
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
          <p className="text-xs text-muted">
            Settings from the image:{" "}
            {[...settings.map((r) => `${r.label} ${r.value}`), ...loras].join(" · ")}
          </p>
        )}
        {error && <p className="text-xs text-danger">{error}</p>}
        <DialogActions>
          <Button onClick={close}>Cancel</Button>
          <button type="submit" disabled={saving || adding > 0} className={PRIMARY}>
            {editor.mode === "new" ? "Save" : "Save changes"}
          </button>
        </DialogActions>
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
