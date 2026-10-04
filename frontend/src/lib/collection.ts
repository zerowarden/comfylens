import type { QueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type {
  CollectionImage,
  Draft,
  ImportResponse,
  PromptInput,
  PromptSettings,
  SavedLora,
  SavedPrompt,
} from "../api/types";
import { useCollection } from "../state/collection";
import { useFileActions } from "../state/fileActions";
import { emptyFilters, useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import { chunks, TRASH_BATCH } from "./files";
import { fmtInt } from "./format";
import { viewHash } from "./viewHash";

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * After a collection write: refetch the collection and the grid pages (their saved badges). When
 * the filters depend on the collection, everything they scope is stale too.
 */
export function refreshAfterCollectionWrite(client: QueryClient): void {
  const { filters } = useFilters.getState();
  const scoped = filters.saved !== null || filters.saved_prompt !== null;
  const keep = new Set(["library", "index-status", "image", "raw"]);
  void client.invalidateQueries({
    predicate: (q) => {
      const head = q.queryKey[0] as string;
      return head === "collection" || head === "page" || (scoped && !keep.has(head));
    },
  });
}

/**
 * Several dropped files make one prompt: the first draft with generation metadata (else the
 * first) gives the text and settings, and every image becomes a reference, in drop order.
 */
export function seedDraft(drafts: Draft[]): { draft: Draft; references: CollectionImage[] } | null {
  const first = drafts.find((d) => d.metadata !== "none") ?? drafts[0];
  if (!first) return null;
  const seen = new Set<string>();
  const references: CollectionImage[] = [];
  for (const d of drafts) {
    if (d.original && !seen.has(d.original.content_hash)) {
      seen.add(d.original.content_hash);
      references.push(d.original);
    }
  }
  return { draft: first, references };
}

/** Tags typed as "a, b , a" -> ["a", "b"]; the server normalizes case and spacing again. */
export function parseTags(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const tag = raw.trim().replace(/\s+/g, " ").toLowerCase();
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

export function emptySettings(): PromptSettings {
  return {
    base_model: null,
    seed: null,
    steps: null,
    cfg: null,
    sampler_name: null,
    scheduler: null,
    denoise: null,
    guidance: null,
    shift: null,
    loras: [],
  };
}

/** The editable fields of a saved prompt, as the editor starts with them. */
export function inputOf(prompt: SavedPrompt): PromptInput {
  return {
    title: prompt.title,
    positive: prompt.positive,
    negative: prompt.negative,
    notes: prompt.notes,
    source_url: prompt.source_url,
    model_family: prompt.model_family,
    tags: prompt.tags,
    settings: prompt.settings,
    references: prompt.references.map((r) => r.content_hash),
    attempts: [],
  };
}

export function inputOfDraft(draft: Draft, references: CollectionImage[]): PromptInput {
  return {
    title: draft.title,
    positive: draft.positive,
    negative: draft.negative,
    notes: "",
    source_url: null,
    model_family: draft.model_family,
    tags: [],
    settings: draft.settings,
    references: references.map((r) => r.content_hash),
    attempts: [],
  };
}

/** Open the editor on a draft of a library image. */
export async function saveImageToCollection(id: number): Promise<void> {
  try {
    const draft = await api.draftFromImage(id);
    useCollection.getState().openEditor({
      mode: "new",
      draft,
      references: draft.original ? [draft.original] : [],
    });
  } catch (e) {
    useFileActions
      .getState()
      .notify({ text: `Could not read the image: ${errorText(e)}`, tone: "error" });
  }
}

/** Open the editor on a prompt's text, e.g. a distinct prompt from prompt analysis. */
export async function saveTextToCollection(positive: string): Promise<void> {
  try {
    const draft = await api.draftFromText({ positive, negative: "" });
    useCollection.getState().openEditor({ mode: "new", draft, references: [] });
  } catch (e) {
    useFileActions
      .getState()
      .notify({ text: `Could not start a saved prompt: ${errorText(e)}`, tone: "error" });
  }
}

/** Open the editor on drafts of dropped, picked or pasted files, uploaded one at a time. */
export async function draftFiles(files: File[]): Promise<void> {
  const { notify } = useFileActions.getState();
  const drafts: Draft[] = [];
  const failures: string[] = [];
  for (const [i, file] of files.entries()) {
    if (files.length > 1) {
      notify({ text: `Reading ${i + 1} of ${files.length} images`, tone: "info", sticky: true });
    }
    try {
      drafts.push(await api.draftFromFile(file));
    } catch (e) {
      failures.push(`${file.name || "pasted image"}: ${errorText(e)}`);
    }
  }
  if (failures.length > 0) notify({ text: failures.join("; "), tone: "error" });
  else if (files.length > 1) notify(null);
  const seeded = seedDraft(drafts);
  if (seeded) useCollection.getState().openEditor({ mode: "new", ...seeded });
}

/** Link library images to a saved prompt, TRASH_BATCH per request. */
export async function linkImages(client: QueryClient, promptId: number, ids: number[]) {
  const { notify } = useFileActions.getState();
  let added = 0;
  let skipped = 0;
  try {
    for (const batch of chunks(ids, TRASH_BATCH)) {
      const result = await api.linkAttempts(promptId, batch);
      added += result.added;
      skipped += result.skipped.length;
    }
    const rest = skipped > 0 ? `; ${fmtInt(skipped)} could not be linked` : "";
    const already = ids.length - added - skipped;
    const known = already > 0 ? `; ${fmtInt(already)} already linked` : "";
    notify({ text: `Linked ${fmtInt(added)} images${known}${rest}`, tone: "info" });
  } catch (e) {
    notify({ text: `Could not link the images: ${errorText(e)}`, tone: "error" });
  }
  refreshAfterCollectionWrite(client);
}

/** Show the library filtered to one saved prompt's images. */
export function showInLibrary(promptId: number): void {
  useFilters.setState({ filters: { ...emptyFilters(), saved_prompt: promptId } });
  useSelection.getState().clear();
  useCollection.getState().openPrompt(null);
  useUi.getState().setView("library");
}

/** Open a saved prompt in the collection view, e.g. from the library's detail view. */
export function openSavedPrompt(promptId: number): void {
  const ui = useUi.getState();
  ui.openDetail(null);
  ui.openCompare(null);
  ui.setView("collection");
  useCollection.getState().openPrompt(promptId);
}

/** Keep the view and the open saved prompt in the URL hash. */
export function syncViewToUrl(): () => void {
  const write = () => {
    const hash = viewHash({
      view: useUi.getState().view,
      promptId: useCollection.getState().openId,
    });
    if (hash === window.location.hash) return;
    const url = `${window.location.pathname}${window.location.search}${hash}`;
    window.history.replaceState(null, "", url);
  };
  const stopUi = useUi.subscribe(write);
  const stopCollection = useCollection.subscribe(write);
  return () => {
    stopUi();
    stopCollection();
  };
}

/** A saved prompt's known settings as label/value rows, in a fixed order; LoRAs excluded. */
export function promptSettingsRows(s: PromptSettings): { label: string; value: string }[] {
  const rows: [string, string | number | null][] = [
    ["base model", s.base_model],
    ["sampler", s.sampler_name],
    ["scheduler", s.scheduler],
    ["steps", s.steps],
    ["cfg", s.cfg],
    ["guidance", s.guidance],
    ["shift", s.shift],
    ["denoise", s.denoise],
    ["seed", s.seed],
  ];
  return rows
    .filter((row): row is [string, string | number] => row[1] !== null && row[1] !== "")
    .map(([label, value]) => ({ label, value: String(value) }));
}

/** "fox 0.8", or "fox 0.8 / 1" when the clip strength differs. */
export function loraText(l: SavedLora): string {
  const model = l.strength_model ?? "?";
  const clip = l.strength_clip !== null && l.strength_clip !== l.strength_model;
  return `${l.name} ${model}${clip ? ` / ${l.strength_clip}` : ""}`;
}

/** The editor fields an added image's metadata can fill in. */
export interface DraftFields {
  title: string;
  positive: string;
  negative: string;
  family: string;
  settings: PromptSettings;
}

function settingsEmpty(s: PromptSettings): boolean {
  return s.loras.length === 0 && promptSettingsRows(s).length === 0;
}

/** References with the drafts' images appended, in order, without duplicates. */
export function appendReferences(
  references: CollectionImage[],
  drafts: Draft[],
): CollectionImage[] {
  const out = [...references];
  for (const d of drafts) {
    if (d.original && !out.some((r) => r.content_hash === d.original!.content_hash)) {
      out.push(d.original);
    }
  }
  return out;
}

/**
 * Fill the fields the user left empty from the first added image that carries generation
 * metadata; never overwrite what is already there.
 */
export function fillEmptyFields(fields: DraftFields, drafts: Draft[]): DraftFields {
  const source = drafts.find((d) => d.metadata !== "none");
  if (!source) return fields;
  return {
    title: fields.title.trim() ? fields.title : source.title,
    positive: fields.positive.trim() ? fields.positive : source.positive,
    negative: fields.negative.trim() ? fields.negative : source.negative,
    family: fields.family.trim() ? fields.family : (source.model_family ?? ""),
    settings: settingsEmpty(fields.settings) ? source.settings : fields.settings,
  };
}

/** Image files among dropped or pasted ones. */
export function imageFiles(files: Iterable<File>): File[] {
  return [...files].filter((f) => f.type === "" || f.type.startsWith("image/"));
}

/** "Imported 3 prompts (2 were already here)", from an import's counts. */
export function importSummary(r: ImportResponse): string {
  const plural = (n: number) => `${fmtInt(n)} ${n === 1 ? "prompt" : "prompts"}`;
  if (r.added === 0 && r.skipped === 0) return "The archive holds no prompts";
  if (r.added === 0) return `Nothing new: all ${plural(r.skipped)} were already here`;
  const already = r.skipped > 0 ? ` (${fmtInt(r.skipped)} already here)` : "";
  return `Imported ${plural(r.added)}${already}`;
}

/** Add an exported archive's prompts to the collection and report what changed. */
export async function importCollection(client: QueryClient, file: File): Promise<void> {
  const { notify } = useFileActions.getState();
  notify({ text: `Importing ${file.name}…`, tone: "info", sticky: true });
  try {
    notify({ text: importSummary(await api.importCollection(file)), tone: "info" });
  } catch (e) {
    notify({ text: `Could not import ${file.name}: ${errorText(e)}`, tone: "error" });
  }
  refreshAfterCollectionWrite(client);
}
