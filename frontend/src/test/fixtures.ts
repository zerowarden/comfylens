import type { ImageItem } from "../api/types";

/** A grid item for tests; only the id and the path vary, the rest is any valid image. */
export function imageItem(id: number, relPath = `${id}.png`): ImageItem {
  return {
    id,
    content_hash: `h${id}`,
    rel_path: relPath,
    width: 16,
    height: 16,
    generated_at: id,
    status: "ok",
    timestamp_suspect: false,
    saved: false,
    tags: [],
  };
}
