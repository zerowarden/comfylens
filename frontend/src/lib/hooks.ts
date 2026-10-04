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

export async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}
