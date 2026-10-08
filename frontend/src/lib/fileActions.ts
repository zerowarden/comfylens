import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { api } from "../api/client";
import type { FileFailure, IdsResponse, ImageDetail, ImagesPage } from "../api/types";
import { useFileActions, type Notice } from "../state/fileActions";
import { useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import {
  baseName,
  chunks,
  nextRemaining,
  removeFromPages,
  retag,
  TRASH_BATCH,
  updateItems,
  withBaseName,
} from "./files";
import { errorText, fmtInt } from "./format";
import { orderKey, PAGE_SIZE } from "./images";

// Every edit changes the caches first and sends the request after: the grid never waits for the
// server. Once the server answers, `refresh` replaces the guesses with its data.

/** An image's path and tags as the caches know them, without a request; null if no cache holds
 * it. */
export function cachedFile(
  client: QueryClient,
  id: number,
): { rel_path: string; tags: string[] } | null {
  const detail = client.getQueryData<ImageDetail>(["image", id]);
  if (detail) return detail.file;
  const pages = client.getQueriesData<ImagesPage>({ queryKey: ["page"] });
  return pages.flatMap(([, page]) => page?.items ?? []).find((i) => i.id === id) ?? null;
}

export const cachedRelPath = (client: QueryClient, id: number) =>
  cachedFile(client, id)?.rel_path ?? null;

/** A single image's file name, else the number of images, for notices. */
function label(client: QueryClient, ids: number[]): string {
  const single = ids.length === 1 ? cachedRelPath(client, ids[0]!) : null;
  return single ? baseName(single) : `${fmtInt(ids.length)} images`;
}

/**
 * After a success the server's snapshot version has moved, and the top bar refetches every query
 * once it sees that. After a failure, refetch everything here: that also undoes the guess.
 */
function refresh(client: QueryClient, failed: boolean): void {
  if (failed) void client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "index-status" });
  else void client.invalidateQueries({ queryKey: ["library"] });
}

export async function renameImage(
  client: QueryClient,
  id: number,
  relPath: string,
  name: string,
): Promise<void> {
  const { notify } = useFileActions.getState();
  const next = withBaseName(relPath, name);
  // A fetch already under way would land after the guess and put the old name back.
  await client.cancelQueries({
    predicate: (q) =>
      q.queryKey[0] === "page" || (q.queryKey[0] === "image" && q.queryKey[1] === id),
  });
  client.setQueriesData<ImagesPage>({ queryKey: ["page"] }, (page) =>
    page ? updateItems(page, new Set([id]), (item) => ({ ...item, rel_path: next })) : page,
  );
  client.setQueryData<ImageDetail>(["image", id], (d) =>
    d ? { ...d, file: { ...d.file, rel_path: next } } : d,
  );
  try {
    await api.rename(id, name);
    notify({ text: `Renamed to ${name}`, tone: "info" });
    refresh(client, false);
  } catch (e) {
    notify({ text: `Could not rename ${baseName(relPath)}: ${errorText(e)}`, tone: "error" });
    refresh(client, true);
  }
}

/**
 * Save a copy of an image without its metadata, through the browser's downloads. The server reads
 * the original and never changes it.
 */
export async function exportStripped(client: QueryClient, id: number): Promise<void> {
  const { notify } = useFileActions.getState();
  const relPath = cachedRelPath(client, id);
  const label = relPath ? baseName(relPath) : "the image";
  try {
    const { blob, name } = await api.stripped(id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name ?? (relPath ? baseName(relPath) : `image-${id}`);
    link.click();
    // Revoked later: some browsers read the URL after click() returns.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    notify({ text: `Exported ${link.download} without metadata`, tone: "info" });
  } catch (e) {
    notify({ text: `Could not export ${label}: ${errorText(e)}`, tone: "error" });
  }
}

/** Take `gone` out of every cached id list and its pages, the selection and the open views. */
function hide(client: QueryClient, gone: ReadonlySet<number>): void {
  const { filters, sort } = useFilters.getState();
  const order = client.getQueryData<IdsResponse>(["ids", orderKey(filters, sort)])?.ids ?? [];
  closeViewsOf(order, gone);
  useSelection.getState().remove(gone);
  for (const [idsKey, data] of client.getQueriesData<IdsResponse>({ queryKey: ["ids"] })) {
    if (data) removeFromIdList(client, idsKey, data.ids, gone);
  }
}

/** Step the detail view on from a removed image, as the arrow keys would; close a comparison
 * holding one. */
function closeViewsOf(order: number[], gone: ReadonlySet<number>): void {
  const ui = useUi.getState();
  if (ui.detailId !== null && gone.has(ui.detailId)) {
    ui.openDetail(nextRemaining(order, ui.detailId, gone));
  }
  if (ui.compareIds?.some((id) => gone.has(id))) ui.openCompare(null);
}

/** Take `gone` out of one cached id list and the cached pages of its order. */
function removeFromIdList(
  client: QueryClient,
  idsKey: QueryKey,
  ids: number[],
  gone: ReadonlySet<number>,
): void {
  const key = idsKey[1];
  const cached = client.getQueriesData<ImagesPage>({ queryKey: ["page", key] });
  const pages = new Map(
    cached.flatMap(([pageKey, page]) => (page ? [[pageKey[2] as number, page] as const] : [])),
  );
  for (const [p, page] of removeFromPages(ids, pages, gone, PAGE_SIZE)) {
    client.setQueryData(["page", key, p], page);
  }
  client.setQueryData<IdsResponse>(idsKey, { ids: ids.filter((id) => !gone.has(id)) });
}

/**
 * Send `ids` TRASH_BATCH per request, with a progress notice while several batches run. Returns
 * every failure; a request that fails counts for its whole batch.
 */
async function inBatches(
  ids: number[],
  progress: string,
  send: (batch: number[]) => Promise<{ failed: FileFailure[] }>,
): Promise<FileFailure[]> {
  const { notify } = useFileActions.getState();
  const failed: FileFailure[] = [];
  const batches = chunks(ids, TRASH_BATCH);
  for (const [i, batch] of batches.entries()) {
    if (batches.length > 1) {
      notify({
        text: `${progress}: ${fmtInt(i * TRASH_BATCH)} of ${fmtInt(ids.length)}`,
        tone: "info",
        sticky: true,
      });
    }
    try {
      failed.push(...(await send(batch)).failed);
    } catch (e) {
      failed.push(...batch.map((id) => ({ id, message: errorText(e) })));
    }
  }
  return failed;
}

/** The notice after a batched edit: `success`, or how many succeeded, how many failed and why. */
function outcome(
  total: number,
  failed: FileFailure[],
  success: string,
  done: (count: string) => string,
  verb: string,
): Notice {
  if (failed.length === 0) return { text: success, tone: "info" };
  const succeeded = total - failed.length;
  const count = failed.length === 1 ? "1 image" : `${fmtInt(failed.length)} images`;
  return {
    text: `${succeeded > 0 ? `${done(fmtInt(succeeded))}; ` : ""}${count} could not be ${verb}: ${failed[0]!.message}`,
    tone: "error",
  };
}

/** Move images to the system trash, TRASH_BATCH per request, reporting progress and failures. */
export async function trashImages(client: QueryClient, ids: number[]): Promise<void> {
  const { notify } = useFileActions.getState();
  const name = label(client, ids);
  await client.cancelQueries({
    predicate: (q) => ["ids", "page"].includes(q.queryKey[0] as string),
  });
  hide(client, new Set(ids));
  const failed = await inBatches(ids, "Moving to the trash", api.trash);
  const moved = (n: string) => `Moved ${n} to the trash`;
  notify(outcome(ids.length, failed, moved(name), moved, "moved"));
  refresh(client, failed.length > 0);
}

/**
 * Remove, then add tags on images, TRASH_BATCH per request. The server writes them into the image
 * files.
 */
export async function tagImages(
  client: QueryClient,
  ids: number[],
  add: string[],
  remove: string[],
): Promise<void> {
  const { notify } = useFileActions.getState();
  const name = label(client, ids);
  const changed = new Set(ids);
  await client.cancelQueries({
    predicate: (q) =>
      q.queryKey[0] === "page" ||
      (q.queryKey[0] === "image" && changed.has(q.queryKey[1] as number)),
  });
  client.setQueriesData<ImagesPage>({ queryKey: ["page"] }, (page) =>
    page ? updateItems(page, changed, (i) => ({ ...i, tags: retag(i.tags, add, remove) })) : page,
  );
  client.setQueriesData<ImageDetail>({ queryKey: ["image"] }, (d) =>
    d && changed.has(d.file.id)
      ? { ...d, file: { ...d.file, tags: retag(d.file.tags, add, remove) } }
      : d,
  );
  const failed = await inBatches(ids, "Tagging", (batch) => api.tag(batch, add, remove));
  notify(
    outcome(ids.length, failed, `Updated the tags of ${name}`, (n) => `Tagged ${n}`, "tagged"),
  );
  refresh(client, failed.length > 0);
}
