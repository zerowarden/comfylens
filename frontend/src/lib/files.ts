import type { ImageItem, ImagesPage } from "../api/types";

/** Ids per trash request: TRASH_BATCH in src/comfylens/api/schemas.py. */
export const TRASH_BATCH = 500;

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
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
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
  const known = new Map<number, ImageItem>();
  for (const page of pages.values()) for (const item of page.items) known.set(item.id, item);
  const kept = order.filter((id) => !gone.has(id));
  const out = new Map<number, ImagesPage>();
  for (const p of pages.keys()) {
    const items: ImageItem[] = [];
    for (const id of kept.slice(p * pageSize, (p + 1) * pageSize)) {
      const item = known.get(id);
      if (!item) break;
      items.push(item);
    }
    out.set(p, { total: kept.length, offset: p * pageSize, items });
  }
  return out;
}

export function renameInPage(page: ImagesPage, id: number, relPath: string): ImagesPage {
  if (!page.items.some((item) => item.id === id)) return page;
  return {
    ...page,
    items: page.items.map((item) => (item.id === id ? { ...item, rel_path: relPath } : item)),
  };
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
  for (let i = index + 1; i < order.length; i++) if (!gone.has(order[i]!)) return order[i]!;
  for (let i = index - 1; i >= 0; i--) if (!gone.has(order[i]!)) return order[i]!;
  return null;
}
