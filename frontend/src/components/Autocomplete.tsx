import {
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type InputHTMLAttributes,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

import type { FacetValue } from "../api/types";
import { fmtInt } from "../lib/format";
import { indexSuggestions, splitMatch, suggest, type Indexed } from "../lib/suggest";
import { FIELD } from "./ui";

/** Rows at most: the list never scrolls, and stays cheap to render. */
const SHOWN = 8;
const ROW_HEIGHT = 26;
const GAP = 2;
const NONE: ReadonlySet<string> = new Set();

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string;
  onChange: (value: string) => void;
  /** A suggestion was chosen, by click or by Enter on the highlighted row. */
  onPick: (value: string) => void;
  /** Most used first, as facets come. */
  options: readonly FacetValue[] | undefined;
  /** Values not to suggest, e.g. tags already added. */
  exclude?: ReadonlySet<string>;
};

/** Below the input, or above it when the viewport has more room there. */
function placement(box: DOMRect, rows: number): CSSProperties {
  const height = rows * ROW_HEIGHT + 8;
  const below = window.innerHeight - box.bottom;
  const vertical =
    below >= height || below >= box.top
      ? { top: box.bottom + GAP }
      : { bottom: window.innerHeight - box.top + GAP };
  return { ...vertical, left: box.left, width: box.width };
}

/** A text field with a list of suggestions that match what is typed, in place of a datalist. */
export default function Autocomplete({
  value,
  onChange,
  onPick,
  options,
  exclude = NONE,
  className = FIELD,
  ...input
}: Props) {
  const listId = useId();
  const field = useRef<HTMLInputElement>(null);
  const [box, setBox] = useState<DOMRect | null>(null);
  const [active, setActive] = useState(-1);
  const index = useMemo(() => indexSuggestions(options), [options]);
  // Typing never waits for filtering: it runs on the deferred value.
  const query = useDeferredValue(value);
  const items = useMemo(() => suggest(index, query, exclude, SHOWN), [index, query, exclude]);
  const open = box !== null && items.length > 0;
  const highlighted = open ? active : -1;

  // Placed once when opened: a scroll or resize closes the list rather than leave it behind.
  useEffect(() => {
    if (box === null) return;
    const close = () => setBox(null);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [box]);

  const show = () => setBox(field.current?.getBoundingClientRect() ?? null);
  const close = () => {
    setBox(null);
    setActive(-1);
  };
  const pick = (item: Indexed) => {
    onPick(item.value);
    close();
  };
  // Through -1 (nothing highlighted), so Enter can still submit what was typed.
  const move = (step: number) => {
    const span = items.length + 1;
    setActive((a) => ((a + 1 + step + span) % span) - 1);
  };

  // Each key: whether it applies now, and what it does.
  const keys: Partial<Record<string, [boolean, () => void]>> = {
    ArrowDown: [true, () => (open ? move(1) : show())],
    ArrowUp: [open, () => move(-1)],
    Enter: [highlighted >= 0, () => pick(items[highlighted]!)],
    Escape: [open, close],
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const [applies, run] = keys[e.key] ?? [false, () => {}];
    if (!applies) return;
    e.preventDefault();
    e.stopPropagation(); // Escape closes the list, not the dialog around it
    run();
  };

  return (
    <>
      <input
        {...input}
        ref={field}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setActive(-1);
          show();
        }}
        onClick={show}
        onBlur={close}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={highlighted >= 0 ? `${listId}-${highlighted}` : undefined}
        autoComplete="off"
        spellCheck={false}
        className={className}
      />
      <SuggestionList
        id={listId}
        box={box}
        items={items}
        query={query}
        active={highlighted}
        onHover={setActive}
        onPick={pick}
      />
    </>
  );
}

/** The open list, in a portal: a dialog's scrolling or clipping never cuts it off. */
function SuggestionList({
  id,
  box,
  items,
  query,
  active,
  onHover,
  onPick,
}: {
  id: string;
  /** The field's box when the list was opened; null while closed. */
  box: DOMRect | null;
  items: Indexed[];
  query: string;
  active: number;
  onHover: (index: number) => void;
  onPick: (item: Indexed) => void;
}) {
  if (box === null || items.length === 0) return null;
  return createPortal(
    <ul
      id={id}
      role="listbox"
      style={placement(box, items.length)}
      // Pressing a row must not blur the field, which would close the list before the click.
      onMouseDown={(e) => e.preventDefault()}
      className="fixed z-[90] overflow-hidden rounded border border-control bg-surface py-1 text-xs shadow-lg motion-safe:animate-expand"
    >
      {items.map((item, i) => {
        const [before, match, after] = splitMatch(item.value, query);
        return (
          <li
            key={item.value}
            id={`${id}-${i}`}
            role="option"
            aria-selected={i === active}
            onMouseEnter={() => onHover(i)}
            onClick={() => onPick(item)}
            style={{ height: ROW_HEIGHT }}
            className={`flex cursor-pointer items-center gap-2 px-2 ${i === active ? "bg-hover" : ""}`}
          >
            <span className="min-w-0 flex-1 truncate text-soft">
              {before}
              <span className="font-semibold text-fg">{match}</span>
              {after}
            </span>
            <span className="shrink-0 text-muted tabular-nums">{fmtInt(item.count)}</span>
          </li>
        );
      })}
    </ul>,
    document.body,
  );
}
