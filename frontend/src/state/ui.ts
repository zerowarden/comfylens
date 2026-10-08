import { create } from "zustand";

import { initialViewState, type View } from "../lib/viewHash";

export type Tab = "overview" | "tags" | "loras" | "configs" | "prompts" | "resolution";
type Theme = "dark" | "light";

function stored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const value = window.localStorage.getItem(key);
    return value !== null && (allowed as readonly string[]).includes(value)
      ? (value as T)
      : fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private window): the setting lasts for this page only.
  }
}

/** Switches the palette in theme.css; runs before React renders so charts read the new colours. */
function applyTheme(theme: Theme): void {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }
}

interface UiStore {
  view: View;
  tileSize: number;
  detailId: number | null;
  /** The image the detail view keeps on screen while it fades out after closing. */
  lastDetailId: number | null;
  /** The two images of the Compare view, in grid order; null when it is closed. */
  compareIds: [number, number] | null;
  theme: Theme;
  panelOpen: boolean;
  panelWidth: number;
  /** Set once the panel's width is settled: by its first fit or by a drag of the resizer. */
  panelFitted: boolean;
  tab: Tab;
  setView: (view: View) => void;
  setTileSize: (size: number) => void;
  openDetail: (id: number | null) => void;
  /** Drops the faded-out image once the detail view's exit animation has run. */
  dropDetail: () => void;
  openCompare: (ids: [number, number] | null) => void;
  toggleTheme: () => void;
  setPanelOpen: (open: boolean) => void;
  setPanelWidth: (width: number) => void;
  /** Widens the panel by `overflow` pixels, once per page load and only if not yet resized. */
  fitPanelWidth: (overflow: number) => void;
  setTab: (tab: Tab) => void;
}

export const TILE_MIN = 96;
export const TILE_MAX = 320;
const PANEL_MIN = 320;
const PANEL_MAX = 900;

function clampPanel(width: number): number {
  return Math.min(PANEL_MAX, Math.max(PANEL_MIN, width));
}

const THEME_KEY = "comfylens.theme";

const initialTheme = stored<Theme>(THEME_KEY, "dark", ["dark", "light"]);
applyTheme(initialTheme);

export const useUi = create<UiStore>((set) => ({
  view: initialViewState().view,
  tileSize: 180,
  detailId: null,
  lastDetailId: null,
  compareIds: null,
  theme: initialTheme,
  panelOpen: true,
  panelWidth: 480,
  panelFitted: false,
  tab: "overview",
  setView: (view) => set({ view }),
  setTileSize: (tileSize) => set({ tileSize: Math.min(TILE_MAX, Math.max(TILE_MIN, tileSize)) }),
  // Closing keeps the id around: the view stays on screen until it has faded out.
  openDetail: (detailId) =>
    set(detailId === null ? { detailId } : { detailId, lastDetailId: detailId }),
  dropDetail: () => set({ lastDetailId: null }),
  openCompare: (compareIds) => set({ compareIds }),
  toggleTheme: () =>
    set((s) => {
      const theme: Theme = s.theme === "dark" ? "light" : "dark";
      remember(THEME_KEY, theme);
      applyTheme(theme);
      return { theme };
    }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  setPanelWidth: (width) => set({ panelWidth: clampPanel(width), panelFitted: true }),
  fitPanelWidth: (overflow) =>
    set((s) =>
      s.panelFitted
        ? {}
        : { panelWidth: clampPanel(s.panelWidth + Math.max(0, overflow)), panelFitted: true },
    ),
  setTab: (tab) => set({ tab }),
}));
