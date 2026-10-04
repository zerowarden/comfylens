import { useQueries } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { api } from "../api/client";
import type { ImageItem, ImagesPage, SortKey } from "../api/types";
import { fmtInt } from "../lib/format";
import { useElementWidth } from "../lib/hooks";
import { comparePair } from "../lib/compare";
import { PAGE_SIZE as PAGE, useImageOrder } from "../lib/images";
import { useFileActions } from "../state/fileActions";
import { SORT_KEYS, useFilters } from "../state/filters";
import { hiddenCount, marqueeSelect, useSelection } from "../state/selection";
import { TILE_MAX, TILE_MIN, useUi } from "../state/ui";
import Tile from "./Tile";
import { Button } from "./ui";

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

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function Toolbar({ total }: { total: number }) {
  const sort = useFilters((s) => s.sort);
  const setSort = useFilters((s) => s.setSort);
  const tileSize = useUi((s) => s.tileSize);
  const setTileSize = useUi((s) => s.setTileSize);
  return (
    <div className="flex h-9 shrink-0 items-center gap-3 border-b border-zinc-200 px-3 dark:border-zinc-800">
      <span className="text-zinc-500 tabular-nums">{fmtInt(total)} images</span>
      <div className="flex-1" />
      <label className="flex items-center gap-1 text-xs text-zinc-500">
        Sort
        <select
          value={sort.key}
          onChange={(e) => setSort({ ...sort, key: e.target.value as SortKey })}
          className="rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-zinc-900 dark:border-zinc-700 dark:text-zinc-100"
        >
          {SORT_KEYS.map((k) => (
            <option key={k} value={k} className="bg-white dark:bg-zinc-900">
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
      <label className="flex items-center gap-1 text-xs text-zinc-500">
        Size
        <input
          type="range"
          min={TILE_MIN}
          max={TILE_MAX}
          value={tileSize}
          onChange={(e) => setTileSize(Number(e.target.value))}
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
      <div className="flex h-8 shrink-0 items-center px-3 text-xs text-zinc-500">
        No selection: the analysis covers every image shown. Click, Ctrl+click, Shift+click or drag
        to select.
      </div>
    );
  const hidden = hiddenCount(selected, visible);
  return (
    <div className="flex h-8 shrink-0 items-center gap-2 bg-sky-500/10 px-3 text-sm">
      <span>
        {fmtInt(selected.size)} selected
        {hidden > 0 && <span className="text-zinc-500"> ({fmtInt(hidden)} hidden by filters)</span>}
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
      <span className="text-xs text-zinc-500">Esc clears, Enter opens</span>
    </div>
  );
}

export default function Grid() {
  const { order, filters, sort, key, query } = useImageOrder();
  const tileSize = useUi((s) => s.tileSize);
  const openDetail = useUi((s) => s.openDetail);
  // The detail and Compare views own the keyboard while open.
  const detailOpen = useUi((s) => s.detailId !== null || s.compareIds !== null);
  const selected = useSelection((s) => s.selected);
  const click = useSelection((s) => s.click);
  const selectAllIds = useSelection((s) => s.selectAll);
  const setSelected = useSelection((s) => s.setSelected);
  const clearSelection = useSelection((s) => s.clear);
  const openMenu = useFileActions((s) => s.openMenu);

  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const width = useElementWidth(scroller);
  const inner = Math.max(0, width - 2 * PAD);
  const columns = Math.max(1, Math.floor(inner / tileSize));
  const cell = inner > 0 ? inner / columns : tileSize;
  const rows = Math.ceil(order.length / columns);

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
  const firstIndex = (virtualRows[0]?.index ?? 0) * columns;
  const lastIndex = Math.min(
    order.length - 1,
    ((virtualRows.at(-1)?.index ?? 0) + 1) * columns - 1,
  );
  const pages = useMemo(() => {
    if (lastIndex < 0) return [];
    const out: number[] = [];
    for (let p = Math.floor(firstIndex / PAGE); p <= Math.floor(lastIndex / PAGE); p++) out.push(p);
    return out;
  }, [firstIndex, lastIndex]);
  const pageResults = useQueries({
    queries: pages.map((page) => ({
      queryKey: ["page", key, page],
      queryFn: () => api.images({ filters, sort, offset: page * PAGE, limit: PAGE }),
      staleTime: 60_000,
    })),
  });
  const loaded = new Map<number, ImagesPage>();
  pages.forEach((page, i) => {
    const data = pageResults[i]?.data;
    if (data) loaded.set(page, data);
  });
  const itemAt = (index: number): ImageItem | undefined =>
    loaded.get(Math.floor(index / PAGE))?.items[index % PAGE];

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
      let ids = [id];
      if (current.has(id)) ids = order.filter((i) => current.has(i));
      else click(id, { ctrl: false, shift: false }, order);
      openMenu({ x: e.clientX, y: e.clientY, ids });
    },
    [click, order, openMenu],
  );

  // Keyboard: Ctrl+A selects every filtered image, Esc clears, Enter opens the anchor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (detailOpen || isTyping(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        selectAllIds(order);
      } else if (e.key === "Escape") {
        clearSelection();
      } else if (e.key === "Enter") {
        const anchor = useSelection.getState().anchor;
        if (anchor !== null) openDetail(anchor);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detailOpen, order, selectAllIds, clearSelection, openDetail]);

  // Marquee: drag from anywhere in the grid, tiles included; Ctrl adds to the selection at drag
  // start. A press on a tile stays a click until the pointer moves past DRAG_THRESHOLD.
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  const marqueeRef = useRef<Marquee | null>(null);
  const covered = useCallback(
    (m: Marquee): number[] => {
      const left = Math.min(m.x0, m.x1) - PAD;
      const right = Math.max(m.x0, m.x1) - PAD;
      const top = Math.min(m.y0, m.y1) - PAD;
      const bottom = Math.max(m.y0, m.y1) - PAD;
      const c0 = Math.max(0, Math.floor(left / cell));
      const c1 = Math.min(columns - 1, Math.floor(right / cell));
      const r0 = Math.max(0, Math.floor(top / cell));
      const r1 = Math.min(rows - 1, Math.floor(bottom / cell));
      const ids: number[] = [];
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          const id = order[r * columns + c];
          if (id !== undefined) ids.push(id);
        }
      }
      return ids;
    },
    [cell, columns, rows, order],
  );

  const onMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0 || !scroller) return;
    const rect = scroller.getBoundingClientRect();
    if (e.clientX > rect.left + scroller.clientWidth) return; // the scrollbar
    e.preventDefault();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top + scroller.scrollTop;
    const start: Marquee = {
      x0: x,
      y0: y,
      x1: x,
      y1: y,
      base: useSelection.getState().selected,
      additive: e.ctrlKey || e.metaKey,
      onTile: (e.target as HTMLElement).closest("[data-tile]") !== null,
      moved: false,
    };
    marqueeRef.current = start;
    setMarquee(start);
  };

  useEffect(() => {
    if (!marquee || !scroller) return;
    const onMove = (e: globalThis.MouseEvent) => {
      const current = marqueeRef.current;
      if (!current) return;
      const rect = scroller.getBoundingClientRect();
      const x1 = e.clientX - rect.left;
      const y1 = e.clientY - rect.top + scroller.scrollTop;
      const moved = current.moved || Math.hypot(x1 - current.x0, y1 - current.y0) > DRAG_THRESHOLD;
      if (!moved) return;
      const next = { ...current, x1, y1, moved };
      marqueeRef.current = next;
      setMarquee(next);
      setSelected(marqueeSelect(next.base, covered(next), next.additive));
    };
    const onUp = () => {
      const current = marqueeRef.current;
      if (current?.moved) {
        // The click that follows a drag released over its starting tile must not reselect it.
        const swallow = (c: globalThis.MouseEvent) => c.stopPropagation();
        window.addEventListener("click", swallow, { capture: true, once: true });
        window.setTimeout(() => window.removeEventListener("click", swallow, true));
      } else if (current && !current.onTile && !current.additive) {
        clearSelection(); // click on empty space
      }
      marqueeRef.current = null;
      setMarquee(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [marquee !== null, scroller, covered, setSelected, clearSelection]); // eslint-disable-line react-hooks/exhaustive-deps

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
        {query.isError && <div className="p-4 text-red-600">{query.error.message}</div>}
        {query.isSuccess && order.length === 0 && (
          <div className="p-8 text-center text-zinc-500">No images match the filters.</div>
        )}
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualRows.map((row) => (
            <div
              key={row.key}
              className="absolute flex"
              style={{ top: row.start, left: PAD, height: cell, gap: GAP }}
            >
              {Array.from({ length: columns }, (_, c) => {
                const index = row.index * columns + c;
                // While the id list still holds the previous filter's page, a fetched item can
                // belong to another image. Take the id from the item so the thumbnail and the
                // click target always agree.
                const item = itemAt(index);
                const id = item?.id ?? order[index];
                if (id === undefined) return null;
                return (
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
                );
              })}
            </div>
          ))}
        </div>
        {marquee?.moved && (
          <div
            className="pointer-events-none absolute border border-sky-500 bg-sky-500/10"
            style={{
              left: Math.min(marquee.x0, marquee.x1),
              top: Math.min(marquee.y0, marquee.y1),
              width: Math.abs(marquee.x1 - marquee.x0),
              height: Math.abs(marquee.y1 - marquee.y0),
            }}
          />
        )}
      </div>
    </div>
  );
}
