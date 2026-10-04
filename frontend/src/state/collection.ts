import { create } from "zustand";

import type { CollectionImage, Draft, SavedPrompt } from "../api/types";
import { parseViewHash } from "../lib/viewHash";

/** A new prompt starts from a draft; an edit starts from the saved prompt. */
export type Editor =
  | { mode: "new"; draft: Draft; references: CollectionImage[] }
  | { mode: "edit"; prompt: SavedPrompt };

interface CollectionStore {
  /** The saved prompt shown in the detail modal. */
  openId: number | null;
  editor: Editor | null;
  /** Library images waiting to be linked to a saved prompt the user picks. */
  linking: number[] | null;
  openPrompt: (id: number | null) => void;
  openEditor: (editor: Editor | null) => void;
  openLinking: (ids: number[] | null) => void;
}

const initial = typeof window === "undefined" ? null : parseViewHash(window.location.hash);

export const useCollection = create<CollectionStore>((set) => ({
  openId: initial?.promptId ?? null,
  editor: null,
  linking: null,
  openPrompt: (openId) => set({ openId }),
  openEditor: (editor) => set({ editor }),
  openLinking: (linking) => set({ linking }),
}));
