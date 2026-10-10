import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/**
 * `flag`, but only once it has stayed true for `ms`; it turns off at once. A busy indicator built
 * on it never flashes for fast responses.
 */
export function useDelayedFlag(flag: boolean, ms: number): boolean {
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!flag) return;
    const timer = window.setTimeout(() => setLate(true), ms);
    return () => {
      window.clearTimeout(timer);
      setLate(false);
    };
  }, [flag, ms]);
  return flag && late;
}

export function useElementWidth(element: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return width;
}

/**
 * Put `text` on the clipboard. The Clipboard API needs a secure context, so plain-HTTP origins
 * (the container's http://comfylens.local) fall back to a hidden field and `execCommand`.
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Denied, unfocused or blocked by policy: the legacy path may still work.
    }
  }
  if (!copyWithField(text)) throw new Error("Could not copy to the clipboard");
}

/** The pre-Clipboard-API path: an off-screen field, selected, with one `execCommand` call. */
function copyWithField(text: string): boolean {
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  // Off screen but still selectable; `display: none` cannot be selected.
  field.style.position = "fixed";
  field.style.left = "-9999px";
  document.body.append(field);
  try {
    field.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
  }
}

/**
 * Put an image on the clipboard. The Clipboard API needs a secure context and takes PNG only,
 * so plain-HTTP origins (the container's http://comfylens.local) and other formats fall back
 * to a selected image and `execCommand`.
 */
export async function copyImage(src: string): Promise<void> {
  const response = await fetch(src);
  if (!response.ok) throw new Error(`the image could not be read (${response.status})`);
  const blob = await response.blob();
  const png = blob.type === "image/png" ? blob : await toPng(blob);
  if (navigator.clipboard && typeof ClipboardItem !== "undefined") {
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
      return;
    } catch {
      // Denied, unfocused or blocked by policy: the legacy path may still work.
    }
  }
  if (!(await copyImageWithElement(png))) throw new Error("the browser blocked the clipboard");
}

/** Re-encode an image the server can send (jpeg, webp) as the PNG the clipboard takes. */
async function toPng(blob: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("the image could not be drawn");
    context.drawImage(bitmap, 0, 0);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (png) =>
          png ? resolve(png) : reject(new Error("the image could not be converted to PNG")),
        "image/png",
      ),
    );
  } finally {
    bitmap.close();
  }
}

/** The pre-Clipboard-API path for images: an off-screen image, selected, with one `execCommand`
 * call. */
async function copyImageWithElement(blob: Blob): Promise<boolean> {
  const url = URL.createObjectURL(blob);
  const host = document.createElement("div");
  host.contentEditable = "true";
  // Off screen but still selectable; `display: none` cannot be selected.
  host.style.position = "fixed";
  host.style.left = "-9999px";
  const image = document.createElement("img");
  image.src = url;
  host.append(image);
  document.body.append(host);
  try {
    await image.decode();
    const range = document.createRange();
    range.selectNode(image);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    window.getSelection()?.removeAllRanges();
    host.remove();
    URL.revokeObjectURL(url);
  }
}

/**
 * Keys pressed inside a menu or dialog stop here: the grid, detail and Compare views listen on the
 * window, and must not clear the selection or close themselves on its Escape or Enter.
 */
export function keepKeys(e: { stopPropagation: () => void }) {
  e.stopPropagation();
}
