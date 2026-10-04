import { describe, expect, it } from "vitest";

import {
  clickSelect,
  hiddenCount,
  marqueeSelect,
  rangeBetween,
  selectAll,
  useSelection,
  type Selection,
} from "./selection";

const order = [50, 40, 30, 20, 10]; // ids in the current sort order
const none: Selection = { selected: new Set(), anchor: null };
const plain = { ctrl: false, shift: false };
const ids = (s: Selection) => [...s.selected].sort((a, b) => a - b);

describe("click", () => {
  it("selects only the clicked tile and makes it the anchor", () => {
    const s = clickSelect({ selected: new Set([10, 20]), anchor: 20 }, 40, plain, order);
    expect(ids(s)).toEqual([40]);
    expect(s.anchor).toBe(40);
  });

  it("Ctrl toggles a tile without touching the rest", () => {
    let s = clickSelect(none, 40, plain, order);
    s = clickSelect(s, 20, { ctrl: true, shift: false }, order);
    expect(ids(s)).toEqual([20, 40]);
    s = clickSelect(s, 40, { ctrl: true, shift: false }, order);
    expect(ids(s)).toEqual([20]);
    expect(s.anchor).toBe(40);
  });
});

describe("shift range", () => {
  it("selects from the anchor in sort order, in either direction", () => {
    const start = clickSelect(none, 40, plain, order);
    expect(ids(clickSelect(start, 20, { ctrl: false, shift: true }, order))).toEqual([20, 30, 40]);
    expect(ids(clickSelect(start, 50, { ctrl: false, shift: true }, order))).toEqual([40, 50]);
  });

  it("keeps the anchor, so a second shift-click re-ranges from it", () => {
    let s = clickSelect(none, 40, plain, order);
    s = clickSelect(s, 10, { ctrl: false, shift: true }, order);
    s = clickSelect(s, 30, { ctrl: false, shift: true }, order);
    expect(ids(s)).toEqual([30, 40]);
    expect(s.anchor).toBe(40);
  });

  it("adds the range to the selection with Ctrl", () => {
    let s = clickSelect(none, 50, plain, order);
    s = clickSelect(s, 20, { ctrl: true, shift: false }, order);
    s = clickSelect(s, 10, { ctrl: true, shift: true }, order);
    expect(ids(s)).toEqual([10, 20, 50]);
  });

  it("acts as a plain click without an anchor in the current order", () => {
    expect(ids(clickSelect(none, 30, { ctrl: false, shift: true }, order))).toEqual([30]);
    const hidden: Selection = { selected: new Set([99]), anchor: 99 };
    expect(ids(clickSelect(hidden, 30, { ctrl: false, shift: true }, order))).toEqual([30]);
  });

  it("rangeBetween is inclusive and empty for unknown ids", () => {
    expect(rangeBetween(order, 10, 30)).toEqual([30, 20, 10]);
    expect(rangeBetween(order, 10, 99)).toEqual([]);
  });
});

describe("select all, marquee, hidden", () => {
  it("selects every filtered id", () => {
    expect(ids(selectAll(none, order))).toEqual([10, 20, 30, 40, 50]);
  });

  it("marquee replaces the selection, or adds to it with Ctrl", () => {
    const base = new Set([99]);
    expect([...marqueeSelect(base, [10, 20], false)]).toEqual([10, 20]);
    expect([...marqueeSelect(base, [10, 20], true)].sort((a, b) => a - b)).toEqual([10, 20, 99]);
  });

  it("counts selected ids hidden by filters", () => {
    expect(hiddenCount(new Set([10, 99, 98]), new Set(order))).toBe(2);
  });

  it("the store applies the same rules and clears", () => {
    const store = useSelection.getState();
    store.click(40, plain, order);
    useSelection.getState().click(20, { ctrl: false, shift: true }, order);
    expect([...useSelection.getState().selected].sort((a, b) => a - b)).toEqual([20, 30, 40]);
    useSelection.getState().selectAll(order);
    expect(useSelection.getState().selected.size).toBe(5);
    useSelection.getState().clear();
    expect(useSelection.getState().selected.size).toBe(0);
    expect(useSelection.getState().anchor).toBeNull();
  });
});
