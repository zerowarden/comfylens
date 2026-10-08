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
import type { CollectionImage, PromptInput, PromptSettings, SavedPrompt } from "../../api/types";
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
import Autocomplete from "../Autocomplete";
import { Modal } from "../Modal";
import { Glyph } from "../icons";
import { Button, DialogActions, FIELD, PRIMARY, Thumbnail } from "../ui";

const INPUT = `mt-1 block w-full px-2 py-1 text-sm ${FIELD}`;

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

/** The fields an editor starts from: the draft's, or the saved prompt's. */
const initialInput = (editor: Editor): PromptInput =>
  editor.mode === "new" ? inputOfDraft(editor.draft, editor.references) : inputOf(editor.prompt);

const initialReferences = (editor: Editor): CollectionImage[] =>
  editor.mode === "new" ? editor.references : editor.prompt.references;

/** Pasted references carry no metadata: say so from the start. */
const initialNote = (editor: Editor): string | null =>
  editor.mode === "new" && editor.draft.metadata === "none" && editor.references.length > 0
    ? PASTED_NO_METADATA
    : null;

const savePrompt = (editor: Editor, body: PromptInput) =>
  editor.mode === "new" ? api.createPrompt(body) : api.updatePrompt(editor.prompt.id, body);

const MODE_TEXT = {
  new: { title: "Save to collection", submit: "Save" },
  edit: { title: "Edit saved prompt", submit: "Save changes" },
};

/**
 * While the editor is open, pasted and dropped images go to `onFiles` wherever they land; a text
 * paste carries no files and goes to the focused field as usual. Returns whether files are being
 * dragged over the window.
 */
function useWindowFiles(onFiles: (files: File[], pasted: boolean) => void): boolean {
  const [dragging, setDragging] = useState(false);
  const deliver = useEffectEvent(onFiles);
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = imageFiles(e.clipboardData?.files ?? []);
      if (files.length === 0) return;
      e.preventDefault();
      deliver(files, true);
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
      deliver(imageFiles(e.dataTransfer?.files ?? []), false);
    };
    const listeners = {
      paste: onPaste,
      dragover: onDragOver,
      dragleave: onDragLeave,
      drop: onDrop,
    };
    const entries = Object.entries(listeners) as [string, EventListener][];
    entries.forEach(([type, listener]) => window.addEventListener(type, listener));
    return () => entries.forEach(([type, listener]) => window.removeEventListener(type, listener));
  }, []);
  return dragging;
}

/** The settings read from the reference images, on one line. */
function ImageSettings({ settings }: { settings: PromptSettings }) {
  const parts = [
    ...promptSettingsRows(settings).map((r) => `${r.label} ${r.value}`),
    ...settings.loras.map(loraText),
  ];
  if (parts.length === 0) return null;
  return <p className="text-xs text-muted">Settings from the image: {parts.join(" · ")}</p>;
}

function EditorForm({ editor }: { editor: Editor }) {
  const client = useQueryClient();
  const openEditor = useCollection((s) => s.openEditor);
  const openPrompt = useCollection((s) => s.openPrompt);
  const notify = useFileActions((s) => s.notify);
  const initial = initialInput(editor);
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
  const [references, setReferences] = useState(initialReferences(editor));
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState(initialNote(editor));
  const [adding, setAdding] = useState(0);
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const facets = useCollectionList();
  const close = () => openEditor(null);

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
  const dragging = useWindowFiles((files, pasted) => void addFiles(files, pasted));

  const onSaved = (saved: SavedPrompt) => {
    client.setQueryData(["collection", "prompt", saved.id], saved);
    close();
    refreshAfterCollectionWrite(client);
    if (useUi.getState().view === "collection") openPrompt(saved.id);
    else notify({ text: `Saved “${saved.title}” to the collection`, tone: "info" });
  };

  const submit = async (e: SubmitEvent) => {
    e.preventDefault();
    const problem = !title.trim()
      ? "A title is required."
      : adding > 0
        ? "Wait for the images to finish uploading."
        : null;
    setError(problem);
    if (problem) return;
    setSaving(true);
    try {
      onSaved(
        await savePrompt(editor, {
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
        }),
      );
    } catch (e) {
      setError(errorText(e));
      setSaving(false);
    }
  };

  return (
    <Modal title={MODE_TEXT[editor.mode].title} onClose={close} width="w-[720px]" align="top">
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
            autoComplete="off"
            value={title}
            onChange={(e) => set({ title: e.target.value })}
            maxLength={200}
            autoFocus
            className={INPUT}
          />
        </Field>
        <Field label="Positive prompt">
          <textarea
            autoComplete="off"
            value={positive}
            onChange={(e) => set({ positive: e.target.value })}
            rows={6}
            className={`${INPUT} font-mono text-xs`}
          />
        </Field>
        <Field label="Negative prompt">
          <textarea
            autoComplete="off"
            value={negative}
            onChange={(e) => set({ negative: e.target.value })}
            rows={2}
            className={`${INPUT} font-mono text-xs`}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tags, comma separated">
            <input
              autoComplete="off"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="Model family">
            <Autocomplete
              value={family}
              onChange={(value) => set({ family: value })}
              onPick={(value) => set({ family: value })}
              options={facets.data?.families}
              className={INPUT}
            />
          </Field>
        </div>
        <Field label="Source URL">
          <input
            autoComplete="off"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="Where you found it"
            className={INPUT}
          />
        </Field>
        <Field label="Notes">
          <textarea
            autoComplete="off"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={INPUT}
          />
        </Field>
        <ImageSettings settings={fields.settings} />
        {error && <p className="text-xs text-danger">{error}</p>}
        <DialogActions>
          <Button onClick={close}>Cancel</Button>
          <button type="submit" disabled={saving || adding > 0} className={PRIMARY}>
            {MODE_TEXT[editor.mode].submit}
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
