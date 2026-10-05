import type { QueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { IdsResponse, ImageDetail, ImagesPage, TrashFailure } from "../api/types";
import { useFileActions } from "../state/fileActions";
import { useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import {
  baseName,
  chunks,
  nextRemaining,
  removeFromPages,
  renameInPage,
  TRASH_BATCH,
  withBaseName,
} from "./files";
import { fmtInt } from "./format";
import { orderKey, PAGE_SIZE } from "./images";

// Both edits change the caches first and send the request after: the grid never waits for the
// server. Once the server answers, `refresh` replaces the guesses with its data.

/** An image's path as the caches know it, without a request; null if no cache holds it. */
export function cachedRelPath(client: QueryClient, id: number): string | null {
  const detail = client.getQueryData<ImageDetail>(["image", id]);
  if (detail) return detail.file.rel_path;
  for (const [, page] of client.getQueriesData<ImagesPage>({ queryKey: ["page"] })) {
    const item = page?.items.find((i) => i.id === id);
    if (item) return item.rel_path;
  }
  return null;
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

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
    page ? renameInPage(page, id, next) : page,
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
  const ui = useUi.getState();
  if (ui.detailId !== null && gone.has(ui.detailId)) {
    ui.openDetail(nextRemaining(order, ui.detailId, gone)); // as the arrow keys would step
  }
  if (ui.compareIds?.some((id) => gone.has(id))) ui.openCompare(null);
  useSelection.getState().remove(gone);

  for (const [idsKey, data] of client.getQueriesData<IdsResponse>({ queryKey: ["ids"] })) {
    if (!data) continue;
    const key = idsKey[1];
    const pages = new Map<number, ImagesPage>();
    for (const [pageKey, page] of client.getQueriesData<ImagesPage>({ queryKey: ["page", key] })) {
      if (page) pages.set(pageKey[2] as number, page);
    }
    for (const [p, page] of removeFromPages(data.ids, pages, gone, PAGE_SIZE)) {
      client.setQueryData(["page", key, p], page);
    }
    client.setQueryData<IdsResponse>(idsKey, { ids: data.ids.filter((id) => !gone.has(id)) });
  }
}

/** Move images to the system trash, TRASH_BATCH per request, reporting progress and failures. */
export async function trashImages(client: QueryClient, ids: number[]): Promise<void> {
  const { notify } = useFileActions.getState();
  const single = ids.length === 1 ? cachedRelPath(client, ids[0]!) : null;
  const label = single ? baseName(single) : `${fmtInt(ids.length)} images`;
  await client.cancelQueries({
    predicate: (q) => ["ids", "page"].includes(q.queryKey[0] as string),
  });
  hide(client, new Set(ids));

  let trashed = 0;
  const failed: TrashFailure[] = [];
  const batches = chunks(ids, TRASH_BATCH);
  for (const [i, batch] of batches.entries()) {
    if (batches.length > 1) {
      notify({
        text: `Moving to the trash: ${fmtInt(i * TRASH_BATCH)} of ${fmtInt(ids.length)}`,
        tone: "info",
        sticky: true,
      });
    }
    try {
      const result = await api.trash(batch);
      trashed += result.trashed.length;
      failed.push(...result.failed);
    } catch (e) {
      failed.push(...batch.map((id) => ({ id, message: errorText(e) })));
    }
  }

  if (failed.length === 0) {
    notify({ text: `Moved ${label} to the trash`, tone: "info" });
  } else {
    const moved = trashed > 0 ? `Moved ${fmtInt(trashed)} to the trash; ` : "";
    const count = failed.length === 1 ? "1 image" : `${fmtInt(failed.length)} images`;
    notify({
      text: `${moved}${count} could not be moved: ${failed[0]!.message}`,
      tone: "error",
    });
  }
  refresh(client, failed.length > 0);
}
