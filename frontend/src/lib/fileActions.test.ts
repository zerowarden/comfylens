import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../api/client";
import type {
  IdsResponse,
  ImageDetail,
  ImagesPage,
  TagResponse,
  TrashResponse,
} from "../api/types";
import { useFileActions } from "../state/fileActions";
import { useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useUi } from "../state/ui";
import { imageItem } from "../test/fixtures";
import {
  copyImageToClipboard,
  exportStripped,
  renameImage,
  tagImages,
  trashImages,
} from "./fileActions";
import { TRASH_BATCH } from "./files";
import { copyImage } from "./hooks";
import { orderKey } from "./images";

// The clipboard itself is covered in hooks.test.ts; here only the action around it.
vi.mock("./hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./hooks")>();
  return { ...actual, copyImage: vi.fn() };
});

const item = (id: number) => imageItem(id, `dir/${id}.png`);

let client: QueryClient;
let key: string;
const ids = () => client.getQueryData<IdsResponse>(["ids", key])?.ids;
const pageIds = (p: number) =>
  client.getQueryData<ImagesPage>(["page", key, p])?.items.map((i) => i.id);
const invalidated = (queryKey: unknown[]) => client.getQueryState(queryKey)?.isInvalidated;

/** A promise the test settles, to look at the UI while the request is still out. */
function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  client = new QueryClient();
  const { filters, sort } = useFilters.getState();
  key = orderKey(filters, sort);
  const order = [1, 2, 3, 4, 5];
  client.setQueryData(["ids", key], { ids: order });
  client.setQueryData(["page", key, 0], { total: 5, offset: 0, items: order.map(item) });
  client.setQueryData(["library"], {});
  client.setQueryData(["stats", "x"], {});
  useSelection.setState({ selected: new Set([2, 3]), anchor: 2 });
  useUi.setState({ detailId: null, compareIds: null });
  useFileActions.setState({ notice: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("exportStripped", () => {
  it("saves the copy under the server's name", async () => {
    const blob = new Blob(["png"], { type: "image/png" });
    vi.spyOn(api, "stripped").mockResolvedValue({ blob, name: "4.png" });
    const createObjectURL = vi.fn(() => "blob:copy");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await exportStripped(client, 4);
    expect(api.stripped).toHaveBeenCalledWith(4);
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    const link = click.mock.contexts[0] as HTMLAnchorElement;
    expect(link.href).toBe("blob:copy");
    expect(link.download).toBe("4.png");
    expect(useFileActions.getState().notice).toEqual({
      text: "Exported 4.png without metadata",
      tone: "info",
    });
  });

  it("reports a failure with the cached name", async () => {
    vi.spyOn(api, "stripped").mockRejectedValue(
      new ApiError(422, "cannot_strip", "the PNG ends inside a chunk"),
    );
    await exportStripped(client, 4);
    expect(useFileActions.getState().notice).toEqual({
      text: "Could not export 4.png: the PNG ends inside a chunk",
      tone: "error",
    });
  });
});

describe("copyImageToClipboard", () => {
  it("reports a copy with the cached name", async () => {
    vi.mocked(copyImage).mockResolvedValue(undefined);
    await copyImageToClipboard(client, 4);
    expect(copyImage).toHaveBeenCalledWith("/api/images/4/file");
    expect(useFileActions.getState().notice).toEqual({
      text: "Copied 4.png to the clipboard",
      tone: "info",
    });
  });

  it("reports a failure with the cached name", async () => {
    vi.mocked(copyImage).mockRejectedValue(new Error("the browser blocked the clipboard"));
    await copyImageToClipboard(client, 4);
    expect(useFileActions.getState().notice).toEqual({
      text: "Could not copy 4.png: the browser blocked the clipboard",
      tone: "error",
    });
  });
});

describe("trashImages", () => {
  it("hides the images before the server answers", async () => {
    const request = pending<TrashResponse>();
    vi.spyOn(api, "trash").mockReturnValue(request.promise);
    useUi.setState({ detailId: 3, compareIds: [1, 2] });

    const done = trashImages(client, [2, 3]);
    await vi.waitFor(() => expect(api.trash).toHaveBeenCalledWith([2, 3]));
    expect(ids()).toEqual([1, 4, 5]);
    expect(pageIds(0)).toEqual([1, 4, 5]);
    expect(useSelection.getState().selected.size).toBe(0);
    expect(useSelection.getState().anchor).toBeNull();
    expect(useUi.getState().detailId).toBe(4); // stepped on to the next remaining image
    expect(useUi.getState().compareIds).toBeNull();

    request.resolve({ trashed: [2, 3], failed: [] });
    await done;
    expect(useFileActions.getState().notice).toEqual({
      text: "Moved 2 images to the trash",
      tone: "info",
    });
    // The new snapshot version makes the top bar refresh the rest.
    expect(invalidated(["library"])).toBe(true);
    expect(invalidated(["stats", "x"])).toBe(false);
  });

  it("names a single image by its file name", async () => {
    vi.spyOn(api, "trash").mockResolvedValue({ trashed: [4], failed: [] });
    await trashImages(client, [4]);
    expect(useFileActions.getState().notice?.text).toBe("Moved 4.png to the trash");
  });

  it("sends large selections in batches", async () => {
    const many = Array.from({ length: TRASH_BATCH * 2 + 1 }, (_, i) => i + 100);
    const trash = vi
      .spyOn(api, "trash")
      .mockImplementation(async (batch) => ({ trashed: batch, failed: [] }));
    await trashImages(client, many);
    expect(trash.mock.calls.map(([batch]) => batch.length)).toEqual([TRASH_BATCH, TRASH_BATCH, 1]);
    expect(useFileActions.getState().notice?.text).toBe("Moved 1,001 images to the trash");
  });

  it("reports failures and refetches everything to bring failed images back", async () => {
    vi.spyOn(api, "trash").mockResolvedValue({
      trashed: [2],
      failed: [{ id: 3, message: "dir/3.png: Permission denied" }],
    });
    await trashImages(client, [2, 3]);
    expect(useFileActions.getState().notice).toEqual({
      text: "Moved 1 to the trash; 1 image could not be moved: dir/3.png: Permission denied",
      tone: "error",
    });
    expect(invalidated(["stats", "x"])).toBe(true);
    expect(invalidated(["ids", key])).toBe(true);
  });

  it("treats a failed request as a failure of its whole batch", async () => {
    vi.spyOn(api, "trash").mockRejectedValue(new ApiError(503, "catalog_busy", "busy"));
    await trashImages(client, [2, 3]);
    expect(useFileActions.getState().notice?.text).toBe("2 images could not be moved: busy");
    expect(invalidated(["ids", key])).toBe(true);
  });
});

describe("renameImage", () => {
  beforeEach(() => {
    client.setQueryData(["image", 2], { file: { rel_path: "dir/2.png" } } as ImageDetail);
  });

  it("shows the new name before the server answers", async () => {
    const request = pending<never>();
    vi.spyOn(api, "rename").mockReturnValue(request.promise);
    const done = renameImage(client, 2, "dir/2.png", "fox.png");
    await vi.waitFor(() => expect(api.rename).toHaveBeenCalledWith(2, "fox.png"));
    const page = client.getQueryData<ImagesPage>(["page", key, 0]);
    expect(page?.items[1]?.rel_path).toBe("dir/fox.png");
    expect(client.getQueryData<ImageDetail>(["image", 2])?.file.rel_path).toBe("dir/fox.png");

    request.reject(new ApiError(409, "name_taken", "a file named fox.png already exists"));
    await done;
    expect(useFileActions.getState().notice).toEqual({
      text: "Could not rename 2.png: a file named fox.png already exists",
      tone: "error",
    });
    expect(invalidated(["page", key, 0])).toBe(true); // refetched: the old name comes back
  });

  it("confirms a rename", async () => {
    vi.spyOn(api, "rename").mockResolvedValue({ id: 2, rel_path: "dir/fox.png", generated_at: 2 });
    await renameImage(client, 2, "dir/2.png", "fox.png");
    expect(useFileActions.getState().notice).toEqual({ text: "Renamed to fox.png", tone: "info" });
    expect(invalidated(["library"])).toBe(true);
  });
});

describe("tagImages", () => {
  const tags = (id: number) =>
    client.getQueryData<ImagesPage>(["page", key, 0])?.items.find((i) => i.id === id)?.tags;

  it("shows the new tags before the server answers", async () => {
    client.setQueryData(["image", 2], { file: { id: 2, tags: ["owl"] } } as ImageDetail);
    const request = pending<TagResponse>();
    vi.spyOn(api, "tag").mockReturnValue(request.promise);
    const done = tagImages(client, [2, 3], ["fox"], ["owl"]);
    await vi.waitFor(() => expect(api.tag).toHaveBeenCalledWith([2, 3], ["fox"], ["owl"]));
    expect([tags(1), tags(2), tags(3)]).toEqual([[], ["fox"], ["fox"]]);
    expect(client.getQueryData<ImageDetail>(["image", 2])?.file.tags).toEqual(["fox"]);

    request.resolve({
      tagged: [
        { id: 2, tags: ["fox"] },
        { id: 3, tags: ["fox"] },
      ],
      failed: [],
    });
    await done;
    expect(useFileActions.getState().notice).toEqual({
      text: "Updated the tags of 2 images",
      tone: "info",
    });
    expect(invalidated(["library"])).toBe(true);
    expect(invalidated(["stats", "x"])).toBe(false);
  });

  it("reports failures and refetches everything to undo the guess", async () => {
    vi.spyOn(api, "tag").mockResolvedValue({
      tagged: [{ id: 4, tags: ["fox"] }],
      failed: [{ id: 5, message: "dir/5.png: the file already holds XMP metadata" }],
    });
    await tagImages(client, [4, 5], ["fox"], []);
    expect(useFileActions.getState().notice).toEqual({
      text: "Tagged 1; 1 image could not be tagged: dir/5.png: the file already holds XMP metadata",
      tone: "error",
    });
    expect(invalidated(["page", key, 0])).toBe(true);
  });

  it("sends large selections in batches and names a single image", async () => {
    const many = Array.from({ length: TRASH_BATCH + 1 }, (_, i) => i + 100);
    const tag = vi.spyOn(api, "tag").mockResolvedValue({ tagged: [], failed: [] });
    await tagImages(client, many, ["fox"], []);
    expect(tag.mock.calls.map(([batch]) => batch.length)).toEqual([TRASH_BATCH, 1]);
    await tagImages(client, [4], ["fox"], []);
    expect(useFileActions.getState().notice?.text).toBe("Updated the tags of 4.png");
  });
});
