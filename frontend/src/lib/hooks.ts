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
 * Keys pressed inside a menu or dialog stop here: the grid, detail and Compare views listen on the
 * window, and must not clear the selection or close themselves on its Escape or Enter.
 */
export function keepKeys(e: { stopPropagation: () => void }) {
  e.stopPropagation();
}
