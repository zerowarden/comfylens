import { create } from "zustand";

export type Tab = "overview" | "loras" | "configs" | "prompts" | "resolution" | "advanced";
export type Theme = "dark" | "light";

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

interface UiStore {
  tileSize: number;
  pool: boolean;
  detailId: number | null;
  /** The two images of the Compare view, in grid order; null when it is closed. */
  compareIds: [number, number] | null;
  theme: Theme;
  sidebarOpen: boolean;
  panelOpen: boolean;
  panelWidth: number;
  tab: Tab;
  setTileSize: (size: number) => void;
  setPool: (pool: boolean) => void;
  openDetail: (id: number | null) => void;
  openCompare: (ids: [number, number] | null) => void;
  toggleTheme: () => void;
  setSidebarOpen: (open: boolean) => void;
  setPanelOpen: (open: boolean) => void;
  setPanelWidth: (width: number) => void;
  setTab: (tab: Tab) => void;
}

export const TILE_MIN = 96;
export const TILE_MAX = 320;
export const PANEL_MIN = 320;
export const PANEL_MAX = 900;

export const useUi = create<UiStore>((set) => ({
  tileSize: 180,
  pool: false,
  detailId: null,
  compareIds: null,
  theme: stored<Theme>("comfylens.theme", "dark", ["dark", "light"]),
  sidebarOpen: true,
  panelOpen: true,
  panelWidth: 480,
  tab: "overview",
  setTileSize: (tileSize) => set({ tileSize: Math.min(TILE_MAX, Math.max(TILE_MIN, tileSize)) }),
  setPool: (pool) => set({ pool }),
  openDetail: (detailId) => set({ detailId }),
  openCompare: (compareIds) => set({ compareIds }),
  toggleTheme: () =>
    set((s) => {
      const theme: Theme = s.theme === "dark" ? "light" : "dark";
      remember("comfylens.theme", theme);
      return { theme };
    }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  setPanelWidth: (width) => set({ panelWidth: Math.min(PANEL_MAX, Math.max(PANEL_MIN, width)) }),
  setTab: (tab) => set({ tab }),
}));
