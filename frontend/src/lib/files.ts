import type { ImageItem, ImagesPage } from "../api/types";

/** Ids per trash or tag request: TRASH_BATCH in src/comfylens/api/schemas.py. */
export const TRASH_BATCH = 500;
/** MAX_TAG_LENGTH in src/comfylens/metadata/xmp.py. */
export const MAX_TAG_LENGTH = 64;

export function baseName(relPath: string): string {
  return relPath.slice(relPath.lastIndexOf("/") + 1);
}

/** The path of `relPath` under a new base name, in the same directory. */
export function withBaseName(relPath: string, name: string): string {
  return relPath.slice(0, relPath.lastIndexOf("/") + 1) + name;
}

/** The extension including its dot ("" without one); a leading dot starts no extension. */
export function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot) : "";
}

/**
 * Why `next` cannot replace the base name `current`, or null when it can. Mirrors the server's
 * checks that need no file system, so the dialog catches mistakes before anything is sent.
 */
export function nameProblem(current: string, next: string): string | null {
  const ext = extension(current);
  if (!next.trim()) return "Enter a name.";
  if (next !== next.trim()) return "The name cannot start or end with a space.";
  if (next.includes("/")) return "The name cannot contain a slash.";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return "The name cannot contain control characters.";
  if (new TextEncoder().encode(next).length > 255) return "The name is too long.";
  if (!next.toLowerCase().endsWith(ext.toLowerCase()) || next.length === ext.length)
    return `The name must keep the ${ext} extension.`;
  return null;
}

/** The file name in a Content-Disposition header, as Starlette writes it; null without one. */
export function attachmentName(header: string): string | null {
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]!);
    } catch {
      return null;
    }
  }
  return /filename="([^"]*)"/i.exec(header)?.[1] ?? null;
}

export function chunks<T>(items: readonly T[], size: number): T[][] {
  return Array.from({ length: Math.ceil(items.length / size) }, (_, i) =>
    items.slice(i * size, (i + 1) * size),
  );
}

/**
 * The cached grid pages of one id list once `gone` is removed from `order`. Every remaining image
 * moves up; each page is rebuilt at its new offset from the items already cached, up to the first
 * image no cached page holds. The grid shows a placeholder past that point until the refetch, never
 * another image's thumbnail, and no page is refetched before the server has applied the change.
 */
export function removeFromPages(
  order: readonly number[],
  pages: ReadonlyMap<number, ImagesPage>,
  gone: ReadonlySet<number>,
  pageSize: number,
): Map<number, ImagesPage> {
  const known = new Map(
    [...pages.values()].flatMap((page) => page.items.map((item) => [item.id, item] as const)),
  );
  const kept = order.filter((id) => !gone.has(id));
  const rebuilt = (p: number): ImagesPage => {
    const items = kept.slice(p * pageSize, (p + 1) * pageSize).map((id) => known.get(id));
    const missing = items.indexOf(undefined);
    const cached = (missing < 0 ? items : items.slice(0, missing)) as ImageItem[];
    return { total: kept.length, offset: p * pageSize, items: cached };
  };
  return new Map([...pages.keys()].map((p) => [p, rebuilt(p)]));
}

/** `page` with `change` applied to the items in `ids`; the same page when it holds none. */
export function updateItems(
  page: ImagesPage,
  ids: ReadonlySet<number>,
  change: (item: ImageItem) => ImageItem,
): ImagesPage {
  if (!page.items.some((item) => ids.has(item.id))) return page;
  return { ...page, items: page.items.map((item) => (ids.has(item.id) ? change(item) : item)) };
}

/** The tags typed into a field: comma-separated, trimmed, without empty ones. */
export function splitTags(text: string): string[] {
  return text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** `tags` without `remove`, then with `add`: sorted and unique, as the server stores them. */
export function retag(tags: readonly string[], add: readonly string[], remove: readonly string[]) {
  return [...new Set([...tags.filter((t) => !remove.includes(t)), ...add])].sort();
}

/** Why `tag` cannot be added, or null when it can. Mirrors TagRequest's checks on the server. */
export function tagProblem(tag: string): string | null {
  if ([...tag].length > MAX_TAG_LENGTH) return `A tag is at most ${MAX_TAG_LENGTH} characters.`;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(tag)) return "A tag cannot contain control characters.";
  return null;
}

/**
 * Where the detail view goes when its image is removed: the next remaining image in `order`, else
 * the previous one, else nowhere (null). Null too when `id` is not in `order`.
 */
export function nextRemaining(
  order: readonly number[],
  id: number,
  gone: ReadonlySet<number>,
): number | null {
  const index = order.indexOf(id);
  if (index < 0) return null;
  const remains = (other: number) => !gone.has(other);
  return order.slice(index + 1).find(remains) ?? order.slice(0, index).findLast(remains) ?? null;
}
