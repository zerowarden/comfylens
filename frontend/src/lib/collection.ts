import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Draft, ImportResponse } from "../api/types";
import { useCollection } from "../state/collection";
import { useFileActions } from "../state/fileActions";
import { emptyFilters, useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import { seedDraft } from "./draft";
import { chunks, TRASH_BATCH } from "./files";
import { errorText, fmtInt, plural } from "./format";

/** The saved-prompt list, with one cache key and one stale-data behavior everywhere. */
export function useCollectionList(
  params: { q?: string; tag?: string | null; family?: string | null } = {},
) {
  const { q = "", tag = null, family = null } = params;
  return useQuery({
    queryKey: ["collection", "list", q, tag, family],
    queryFn: () => api.collection({ q, tag, family }),
    placeholderData: keepPreviousData,
  });
}

/** One saved prompt by id; the query is disabled while `id` is null. */
export function useSavedPrompt(id: number | null) {
  return useQuery({
    queryKey: ["collection", "prompt", id],
    queryFn: () => api.savedPrompt(id!),
    enabled: id !== null,
    retry: false,
  });
}

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

/**
 * Upload files one at a time; a failed file becomes a "<name>: <message>" failure. `hooks`
 * report progress and let a caller use each draft as soon as it is stored.
 */
export async function uploadDrafts(
  files: File[],
  hooks: { onDraft?: (draft: Draft) => void; onFile?: (index: number) => void } = {},
): Promise<{ drafts: Draft[]; failures: string[] }> {
  const drafts: Draft[] = [];
  const failures: string[] = [];
  for (const [i, file] of files.entries()) {
    try {
      const draft = await api.draftFromFile(file);
      drafts.push(draft);
      hooks.onDraft?.(draft);
    } catch (e) {
      failures.push(`${file.name || "pasted image"}: ${errorText(e)}`);
    }
    hooks.onFile?.(i);
  }
  return { drafts, failures };
}

/** Open the editor on drafts of dropped, picked or pasted files, uploaded one at a time. */
export async function draftFiles(files: File[]): Promise<void> {
  const { notify } = useFileActions.getState();
  const { drafts, failures } = await uploadDrafts(files, {
    onFile: (i) => {
      if (files.length > 1) {
        notify({ text: `Reading ${i + 1} of ${files.length} images`, tone: "info", sticky: true });
      }
    },
  });
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

/** "Imported 3 prompts (2 were already here)", from an import's counts. */
export function importSummary(r: ImportResponse): string {
  const prompts = (n: number) => plural(n, "prompt");
  if (r.added === 0 && r.skipped === 0) return "The archive holds no prompts";
  if (r.added === 0) return `Nothing new: all ${prompts(r.skipped)} were already here`;
  const already = r.skipped > 0 ? ` (${fmtInt(r.skipped)} already here)` : "";
  return `Imported ${prompts(r.added)}${already}`;
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
