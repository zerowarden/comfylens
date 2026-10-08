import { create } from "zustand";

export interface ContextMenu {
  x: number; // viewport coordinates of the right-click
  y: number;
  ids: number[]; // the images the menu acts on, in grid order
}

type FileDialog =
  | { kind: "rename"; id: number }
  | { kind: "tags"; ids: number[] }
  | { kind: "trash"; ids: number[] };

export interface Notice {
  text: string;
  tone: "info" | "error";
  /** Stays until replaced or dismissed, e.g. while a large trash runs. */
  sticky?: boolean;
}

interface FileActionsStore {
  menu: ContextMenu | null;
  dialog: FileDialog | null;
  notice: Notice | null;
  openMenu: (menu: ContextMenu) => void;
  closeMenu: () => void;
  openDialog: (dialog: FileDialog | null) => void;
  notify: (notice: Notice | null) => void;
}

/** The right-click menu, the rename, tags and trash dialogs, and the notice that reports outcomes. */
export const useFileActions = create<FileActionsStore>((set) => ({
  menu: null,
  dialog: null,
  notice: null,
  openMenu: (menu) => set({ menu }),
  closeMenu: () => set({ menu: null }),
  openDialog: (dialog) => set({ dialog, menu: null }),
  notify: (notice) => set({ notice }),
}));
