import { create } from "zustand";

export interface Selection {
  selected: ReadonlySet<number>;
  anchor: number | null;
}

export interface Modifiers {
  ctrl: boolean; // Ctrl or Cmd
  shift: boolean;
}

/** Ids from `a` to `b` inclusive, in the current sort order; [] if either is absent. */
export function rangeBetween(order: readonly number[], a: number, b: number): number[] {
  const i = order.indexOf(a);
  const j = order.indexOf(b);
  if (i < 0 || j < 0) return [];
  return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

/**
 * Click: select only this tile. Ctrl/Cmd+click: toggle it. Shift+click: the range from the
 * anchor in sort order (added to the selection with Ctrl). The anchor moves on plain and Ctrl
 * clicks only, so successive shift-clicks extend from the same tile.
 */
export function clickSelect(
  current: Selection,
  id: number,
  mods: Modifiers,
  order: readonly number[],
): Selection {
  if (mods.shift && current.anchor !== null) {
    const range = rangeBetween(order, current.anchor, id);
    if (range.length > 0) {
      const selected = mods.ctrl ? new Set([...current.selected, ...range]) : new Set(range);
      return { selected, anchor: current.anchor };
    }
  }
  if (mods.ctrl) {
    const selected = new Set(current.selected);
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    return { selected, anchor: id };
  }
  return { selected: new Set([id]), anchor: id };
}

export function selectAll(current: Selection, order: readonly number[]): Selection {
  return { selected: new Set(order), anchor: current.anchor ?? order[0] ?? null };
}

/** A marquee replaces the selection, or adds to `base` (the selection at drag start) with Ctrl. */
export function marqueeSelect(
  base: ReadonlySet<number>,
  covered: readonly number[],
  additive: boolean,
): ReadonlySet<number> {
  return additive ? new Set([...base, ...covered]) : new Set(covered);
}

/** The selection without `gone` (e.g. trashed images); the anchor goes too if it is among them. */
export function withoutIds(current: Selection, gone: ReadonlySet<number>): Selection {
  const anchor = current.anchor !== null && gone.has(current.anchor) ? null : current.anchor;
  const selected = new Set([...current.selected].filter((id) => !gone.has(id)));
  return selected.size === current.selected.size && anchor === current.anchor
    ? current
    : { selected, anchor };
}

/** Selected ids that the current filters hide. */
export function hiddenCount(selected: ReadonlySet<number>, visible: ReadonlySet<number>): number {
  let hidden = 0;
  for (const id of selected) if (!visible.has(id)) hidden++;
  return hidden;
}

interface SelectionStore extends Selection {
  click: (id: number, mods: Modifiers, order: readonly number[]) => void;
  selectAll: (order: readonly number[]) => void;
  setSelected: (selected: ReadonlySet<number>) => void;
  remove: (gone: ReadonlySet<number>) => void;
  clear: () => void;
}

export const useSelection = create<SelectionStore>((set) => ({
  selected: new Set<number>(),
  anchor: null,
  click: (id, mods, order) => set((s) => clickSelect(s, id, mods, order)),
  selectAll: (order) => set((s) => selectAll(s, order)),
  setSelected: (selected) => set({ selected }),
  remove: (gone) => set((s) => withoutIds(s, gone)),
  clear: () => set({ selected: new Set<number>(), anchor: null }),
}));
