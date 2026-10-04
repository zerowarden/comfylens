import type { ImageItem } from "../api/types";

/** A grid item for tests; only the id and the path vary, the rest is any valid image. */
export function imageItem(id: number, relPath = `${id}.png`): ImageItem {
  return {
    id,
    content_hash: `h${id}`,
    rel_path: relPath,
    width: 16,
    height: 16,
    family: "flux",
    generated_at: id,
    status: "ok",
    has_warnings: false,
    timestamp_suspect: false,
  };
}
