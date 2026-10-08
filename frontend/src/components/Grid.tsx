import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { api } from "../api/client";
import type { Filters, ImageItem, Sort, SortKey } from "../api/types";
import { isTyping } from "../lib/dom";
import { fmtInt } from "../lib/format";
import { useElementWidth } from "../lib/hooks";
import { comparePair } from "../lib/compare";
import { PAGE_SIZE as PAGE, useImageOrder } from "../lib/images";
import { useFileActions } from "../state/fileActions";
import { SORT_KEYS, useFilters } from "../state/filters";
import { hiddenCount, marqueeSelect, useSelection } from "../state/selection";
import { TILE_MAX, TILE_MIN, useUi } from "../state/ui";
import Tile from "./Tile";
import { Button, ErrorState, FIELD, Slider } from "./ui";

const PAD = 8;
const GAP = 6;
const DRAG_THRESHOLD = 4; // px before a press on a tile becomes a marquee instead of a click
const SORT_LABELS: Record<SortKey, string> = {
  generated_at: "Date",
  rel_path: "Path",
  family: "Family",
  steps: "Steps",
  cfg: "CFG",
};

interface Marquee {
  x0: number; // content coordinates
  y0: number;
  x1: number;
  y1: number;
  base: ReadonlySet<number>;
  additive: boolean;
  onTile: boolean;
  moved: boolean;
}

function Toolbar({ total }: { total: number }) {
  const sort = useFilters((s) => s.sort);
  const setSort = useFilters((s) => s.setSort);
  const tileSize = useUi((s) => s.tileSize);
  const setTileSize = useUi((s) => s.setTileSize);
  return (
    <div className="flex h-9 shrink-0 items-center gap-3 border-b border-line px-3">
      <span className="text-muted tabular-nums">{fmtInt(total)} images</span>
      <div className="flex-1" />
      <label className="flex items-center gap-1 text-xs text-muted">
        Sort
        <select
          value={sort.key}
          onChange={(e) => setSort({ ...sort, key: e.target.value as SortKey })}
          className={`px-1 py-0.5 text-fg ${FIELD}`}
        >
          {SORT_KEYS.map((k) => (
            <option key={k} value={k} className="bg-surface">
              {SORT_LABELS[k]}
            </option>
          ))}
        </select>
      </label>
      <Button
        onClick={() => setSort({ ...sort, descending: !sort.descending })}
        title="Sort direction"
      >
        {sort.descending ? "↓ desc" : "↑ asc"}
      </Button>
      <label className="flex items-center gap-1 text-xs text-muted">
        Size
        <Slider
          label="Tile size"
          min={TILE_MIN}
          max={TILE_MAX}
          value={tileSize}
          onChange={setTileSize}
          className="w-24"
        />
      </label>
    </div>
  );
}

function SelectionBanner({ order }: { order: number[] }) {
  const selected = useSelection((s) => s.selected);
  const clear = useSelection((s) => s.clear);
  const openCompare = useUi((s) => s.openCompare);
  const visible = useMemo(() => new Set(order), [order]);
  // Always the same height: a bar that appeared on the first click would push every tile down.
  if (selected.size === 0)
    return (
      <div className="flex h-8 shrink-0 items-center px-3 text-xs text-muted">
        No selection: the analysis covers every image shown. Click, Ctrl+click, Shift+click or drag
        to select.
      </div>
    );
  const hidden = hiddenCount(selected, visible);
  return (
    <div className="flex h-8 shrink-0 items-center gap-2 bg-accent/10 px-3 text-sm">
      <span>
        {fmtInt(selected.size)} selected
        {hidden > 0 && <span className="text-muted"> ({fmtInt(hidden)} hidden by filters)</span>}
      </span>
      <Button onClick={clear}>Clear selection</Button>
      {selected.size === 2 && (
        <Button
          onClick={() => openCompare(comparePair(selected, order))}
          title="Compare the two selected images side by side"
        >
          Compare
        </Button>
      )}
      <span className="text-xs text-muted">Esc clears, Enter opens</span>
    </div>
  );
}

/** The integers from `first` to `last`, both included; none when `last` comes first. */
const range = (first: number, last: number) =>
  Array.from({ length: Math.max(0, last - first + 1) }, (_, i) => first + i);

interface Layout {
  cell: number;
  columns: number;
  rows: number;
}

/** The marquee as a box in content coordinates. */
const marqueeBox = (m: Marquee) => ({
  left: Math.min(m.x0, m.x1),
  top: Math.min(m.y0, m.y1),
  width: Math.abs(m.x1 - m.x0),
  height: Math.abs(m.y1 - m.y0),
});

/** The cells along one axis that a span of the content touches. */
const cellsUnder = (from: number, length: number, cell: number, count: number) =>
  range(
    Math.max(0, Math.floor((from - PAD) / cell)),
    Math.min(count - 1, Math.floor((from + length - PAD) / cell)),
  );

/** The ids of the tiles the marquee touches, row by row. */
function coveredIds(m: Marquee, { cell, columns, rows }: Layout, order: number[]): number[] {
  const box = marqueeBox(m);
  const cols = cellsUnder(box.left, box.width, cell, columns);
  return cellsUnder(box.top, box.height, cell, rows)
    .flatMap((r) => cols.map((c) => order[r * columns + c]))
    .filter((id): id is number => id !== undefined);
}

/** Where a mouse event falls in the scroller's content. */
function contentPoint(scroller: HTMLElement, e: { clientX: number; clientY: number }) {
  const rect = scroller.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top + scroller.scrollTop };
}

/** The click that follows a drag released over its starting tile must not reselect it. */
function swallowNextClick(): void {
  const swallow = (c: globalThis.MouseEvent) => c.stopPropagation();
  window.addEventListener("click", swallow, { capture: true, once: true });
  window.setTimeout(() => window.removeEventListener("click", swallow, true));
}

/**
 * Marquee: drag from anywhere in the grid, tiles included; Ctrl adds to the selection at drag
 * start. A press on a tile stays a click until the pointer moves past DRAG_THRESHOLD; a click on
 * empty space clears the selection.
 */
function useMarquee(scroller: HTMLDivElement | null, covered: (m: Marquee) => number[]) {
  const setSelected = useSelection((s) => s.setSelected);
  const clearSelection = useSelection((s) => s.clear);
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  const marqueeRef = useRef<Marquee | null>(null);
  const show = (m: Marquee | null) => {
    marqueeRef.current = m;
    setMarquee(m);
  };

  const onMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0 || !scroller) return;
    const { x, y } = contentPoint(scroller, e);
    if (x > scroller.clientWidth) return; // the scrollbar
    e.preventDefault();
    show({
      x0: x,
      y0: y,
      x1: x,
      y1: y,
      base: useSelection.getState().selected,
      additive: e.ctrlKey || e.metaKey,
      onTile: (e.target as HTMLElement).closest("[data-tile]") !== null,
      moved: false,
    });
  };

  useEffect(() => {
    if (!marquee || !scroller) return;
    const onMove = (e: globalThis.MouseEvent) => {
      const current = marqueeRef.current;
      if (!current) return;
      const { x: x1, y: y1 } = contentPoint(scroller, e);
      const moved = current.moved || Math.hypot(x1 - current.x0, y1 - current.y0) > DRAG_THRESHOLD;
      if (!moved) return;
      const next = { ...current, x1, y1, moved };
      show(next);
      setSelected(marqueeSelect(next.base, covered(next), next.additive));
    };
    const onUp = () => {
      const current = marqueeRef.current;
      if (current?.moved) swallowNextClick();
      else if (current && !current.onTile && !current.additive) clearSelection();
      show(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [marquee !== null, scroller, covered, setSelected, clearSelection]); // eslint-disable-line react-hooks/exhaustive-deps

  return { marquee, onMouseDown };
}

type GridKey = "selectAll" | "clear" | "open";
const GRID_KEYS: Partial<Record<string, GridKey>> = { Escape: "clear", Enter: "open" };

/** The grid's action for a key press, if any. */
const gridKey = (e: KeyboardEvent): GridKey | undefined =>
  (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" ? "selectAll" : GRID_KEYS[e.key];

/** Keyboard: Ctrl+A selects every filtered image, Esc clears, Enter opens the anchor. The detail
 * and Compare views own the keyboard while open. */
function useGridKeys(order: number[]): void {
  const openDetail = useUi((s) => s.openDetail);
  const viewOpen = useUi((s) => s.detailId !== null || s.compareIds !== null);
  const selectAll = useSelection((s) => s.selectAll);
  const clearSelection = useSelection((s) => s.clear);
  useEffect(() => {
    const actions: Record<GridKey, (e: KeyboardEvent) => void> = {
      selectAll: (e) => {
        e.preventDefault();
        selectAll(order);
      },
      clear: () => clearSelection(),
      open: () => {
        const anchor = useSelection.getState().anchor;
        if (anchor !== null) openDetail(anchor);
      },
    };
    const onKey = (e: KeyboardEvent) => {
      const action = gridKey(e);
      if (action && !viewOpen && !isTyping(e.target)) actions[action](e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewOpen, order, selectAll, clearSelection, openDetail]);
}

/** The grid pages holding the images from `first` to `last`, fetched as they are needed. */
function useVisiblePages(
  { filters, sort, key }: { filters: Filters; sort: Sort; key: string },
  [first, last]: [number, number],
) {
  const pages = useMemo(
    () => (last < 0 ? [] : range(Math.floor(first / PAGE), Math.floor(last / PAGE))),
    [first, last],
  );
  const results = useQueries({
    queries: pages.map((page) => ({
      queryKey: ["page", key, page],
      queryFn: () => api.images({ filters, sort, offset: page * PAGE, limit: PAGE }),
      staleTime: 60_000,
    })),
  });
  const loaded = new Map(
    pages.flatMap((page, i) => {
      const data = results[i]?.data;
      return data ? [[page, data] as const] : [];
    }),
  );
  return (index: number): ImageItem | undefined =>
    loaded.get(Math.floor(index / PAGE))?.items[index % PAGE];
}

/** Columns of tiles at least `tileSize` wide that fill `width`, and the rows `count` needs. */
function gridLayout(width: number, tileSize: number, count: number): Layout {
  const inner = Math.max(0, width - 2 * PAD);
  const columns = Math.max(1, Math.floor(inner / tileSize));
  const cell = inner > 0 ? inner / columns : tileSize;
  return { cell, columns, rows: Math.ceil(count / columns) };
}

/** The indexes of the first and last image in the rendered rows. */
function renderedRange(rows: VirtualItem[], columns: number, count: number): [number, number] {
  const first = rows[0]?.index ?? 0;
  const last = rows.at(-1)?.index ?? 0;
  return [first * columns, Math.min(count - 1, (last + 1) * columns - 1)];
}

/** An error, or the note that no image matches. */
function GridStatus({ query, empty }: { query: UseQueryResult; empty: boolean }) {
  if (query.isError) return <ErrorState error={query.error} />;
  if (query.isSuccess && empty) {
    return <div className="p-8 text-center text-muted">No images match the filters.</div>;
  }
  return null;
}

export default function Grid() {
  const imageOrder = useImageOrder();
  const { order, query } = imageOrder;
  const tileSize = useUi((s) => s.tileSize);
  const openDetail = useUi((s) => s.openDetail);
  const selected = useSelection((s) => s.selected);
  const click = useSelection((s) => s.click);
  const openMenu = useFileActions((s) => s.openMenu);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const { cell, columns, rows } = gridLayout(useElementWidth(scroller), tileSize, order.length);

  // The React Compiler notice for this hook does not apply: this build does not use the compiler.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => scroller,
    estimateSize: () => cell,
    overscan: 4,
    paddingStart: PAD,
    paddingEnd: PAD,
  });
  useEffect(() => virtualizer.measure(), [cell, virtualizer]);

  // Fetch only the pages the visible rows (plus overscan) need.
  const virtualRows = virtualizer.getVirtualItems();
  const itemAt = useVisiblePages(imageOrder, renderedRange(virtualRows, columns, order.length));

  const onTileClick = useCallback(
    (id: number, e: MouseEvent) => {
      e.preventDefault();
      click(id, { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey }, order);
    },
    [click, order],
  );

  // Right-click on a selected tile acts on every selected image the filters show; on any other
  // tile it selects that tile first, as file managers do. The menu opens without a request.
  const onTileContextMenu = useCallback(
    (id: number, e: MouseEvent) => {
      e.preventDefault();
      const { selected: current } = useSelection.getState();
      if (!current.has(id)) click(id, { ctrl: false, shift: false }, order);
      const ids = current.has(id) ? order.filter((i) => current.has(i)) : [id];
      openMenu({ x: e.clientX, y: e.clientY, ids });
    },
    [click, order, openMenu],
  );

  useGridKeys(order);
  const covered = useCallback(
    (m: Marquee) => coveredIds(m, { cell, columns, rows }, order),
    [cell, columns, rows, order],
  );
  const { marquee, onMouseDown } = useMarquee(scroller, covered);

  const size = Math.max(0, cell - GAP);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Toolbar total={order.length} />
      <SelectionBanner order={order} />
      <div
        ref={setScroller}
        onMouseDown={onMouseDown}
        className="relative min-h-0 flex-1 overflow-y-auto select-none"
      >
        <GridStatus query={query} empty={order.length === 0} />
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualRows.map((row) => (
            <div
              key={row.key}
              className="absolute flex"
              style={{ top: row.start, left: PAD, height: cell, gap: GAP }}
            >
              {range(row.index * columns, (row.index + 1) * columns - 1).map((index) => {
                // While the id list still holds the previous filter's page, a fetched item can
                // belong to another image. Take the id from the item so the thumbnail and the
                // click target always agree.
                const item = itemAt(index);
                const id = item?.id ?? order[index];
                return (
                  id !== undefined && (
                    <Tile
                      key={id}
                      id={id}
                      item={item}
                      size={size}
                      selected={selected.has(id)}
                      onClick={onTileClick}
                      onOpen={openDetail}
                      onContextMenu={onTileContextMenu}
                    />
                  )
                );
              })}
            </div>
          ))}
        </div>
        {marquee?.moved && (
          <div
            className="pointer-events-none absolute border border-accent bg-accent/10"
            style={marqueeBox(marquee)}
          />
        )}
      </div>
    </div>
  );
}
