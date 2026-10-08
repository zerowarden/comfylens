import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type TransitionEvent,
} from "react";

import { thumbUrl } from "../api/client";
import { familyColor } from "../lib/colors";
import { fractionOf } from "../lib/format";
import { copyText } from "../lib/hooks";
import { useThumbnailFailure } from "../lib/images";
import { Glyph } from "./icons";

export function Button({
  children,
  onClick,
  active = false,
  disabled = false,
  ghost = false,
  title,
  ariaLabel,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  /** No border until hovered: for icon actions that sit beside content. */
  ghost?: boolean;
  title?: string;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON} disabled:opacity-40 ${
        active
          ? "border-accent bg-accent/15 text-accent-text"
          : `${ghost ? "border-transparent" : "border-control"} hover:bg-hover`
      } ${className}`}
    >
      {children}
    </button>
  );
}

/** Options in a row; the chosen one's highlight slides to the next pick. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);
  const labels = options.map((o) => o.label).join("\0");
  // Measured before paint, and drawn only once measured: the highlight appears in place on the
  // first frame instead of growing from nothing, and slides only on a new pick.
  useLayoutEffect(() => {
    const b = buttons.current.get(value);
    const next = b && { left: b.offsetLeft, width: b.offsetWidth };
    setPill((p) => (p?.left === next?.left && p?.width === next?.width ? p : (next ?? null)));
  }, [value, labels]);
  return (
    <div className="relative inline-flex overflow-hidden rounded border border-control">
      {pill && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 bg-accent/20 transition-[translate,width] duration-(--dur) ease-snappy"
          style={{ translate: `${pill.left}px`, width: pill.width }}
        />
      )}
      {options.map((o) => (
        <button
          key={o.value}
          ref={(b) => {
            if (b) buttons.current.set(o.value, b);
            else buttons.current.delete(o.value);
          }}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`relative px-2 py-0.5 text-xs transition-colors duration-(--dur-fast) ${
            o.value === value ? "text-accent-text" : "hover:bg-hover"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Content that slides open and shut instead of appearing and vanishing at once, so what sits
 * below moves smoothly. Closed, it leaves the DOM once the slide is over.
 */
export function Reveal({ open, children }: { open: boolean; children: ReactNode }) {
  const target = open ? "open" : "closed";
  const [phase, setPhase] = useState<"open" | "closed" | "moving">(target);
  if (phase !== target && phase !== "moving") setPhase("moving");
  const settle = (e: TransitionEvent) => {
    if (e.target === e.currentTarget) setPhase(target);
  };
  return (
    <div
      inert={!open}
      onTransitionEnd={settle}
      className={`grid transition-[grid-template-rows,opacity] duration-(--dur) ease-snappy ${
        open ? "grid-rows-[1fr]" : "grid-rows-[0fr] opacity-0"
      }`}
    >
      {/* Clipped only while it moves or is shut: open, popups and focus rings may overflow. */}
      <div className={`min-h-0 ${phase === "open" ? "" : "overflow-hidden"}`}>
        {phase !== "closed" && children}
      </div>
    </div>
  );
}

export function Collapsible({
  title,
  defaultOpen = false,
  open: controlled,
  onToggle,
  children,
  right,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  /** Controlled mode: pass `open` and `onToggle`. */
  open?: boolean;
  onToggle?: (open: boolean) => void;
  children: ReactNode;
  right?: ReactNode;
}) {
  const [own, setOwn] = useState(defaultOpen);
  const open = controlled ?? own;
  const setOpen = (next: boolean) => {
    if (onToggle) onToggle(next);
    else setOwn(next);
  };
  return (
    <section className="border-b border-line">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex flex-1 items-center gap-2 text-left font-medium"
        >
          <Glyph
            name="chevronRight"
            className={`size-3.5 text-muted transition-transform duration-(--dur) ease-snappy ${open ? "rotate-90" : ""}`}
          />
          {title}
        </button>
        {right}
      </div>
      <Reveal open={open}>
        <div className="px-3 pb-3">{children}</div>
      </Reveal>
    </section>
  );
}

export function ShareBar({
  share,
  tone = "accent",
  className = "w-full",
}: {
  share: number;
  tone?: "accent" | "warning";
  className?: string;
}) {
  return (
    <div className={`h-1.5 ${className} rounded bg-track`}>
      <div
        className={`h-1.5 rounded transition-[width] duration-(--dur) ease-snappy ${
          tone === "warning" ? "bg-warning" : "bg-accent"
        }`}
        style={{ width: `${Math.min(100, share * 100)}%` }}
      />
    </div>
  );
}

/** The cancel/confirm row at the foot of a dialog. */
export function DialogActions({ children }: { children: ReactNode }) {
  return <div className="flex justify-end gap-2">{children}</div>;
}

/** "Show all N" / "Show fewer" for a list cut at a threshold. */
export function ShowAllToggle({
  count,
  all,
  onToggle,
  className = "mt-0.5",
}: {
  count: number;
  all: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`${className} text-xs text-link hover:underline`}
    >
      {all ? "Show fewer" : `Show all ${count}`}
    </button>
  );
}

/** A failed query's message. */
export function ErrorState({ error, className = "p-4" }: { error: Error; className?: string }) {
  return <div className={`${className} text-danger`}>{error.message}</div>;
}

const COPY_STATE = {
  idle: { icon: "copy", suffix: "", className: "" },
  done: { icon: "check", suffix: ": copied", className: "text-success" },
  failed: { icon: "circleAlert", suffix: ": failed", className: "text-danger" },
} as const;

/**
 * A copy-to-clipboard icon for `text` (or the string it resolves to); it turns into a check or an
 * alert to report the outcome. `children` adds a visible caption next to the icon.
 */
export function CopyButton({
  label,
  text,
  children,
}: {
  label: string;
  text: string | (() => Promise<string> | string);
  children?: ReactNode;
}) {
  const [state, setState] = useState<keyof typeof COPY_STATE>("idle");
  const look = COPY_STATE[state];
  return (
    <Button
      ghost
      title={label + look.suffix}
      ariaLabel={label + look.suffix}
      className={`inline-flex items-center gap-1 ${children ? "" : "px-1"}`}
      onClick={() => {
        Promise.resolve(typeof text === "function" ? text() : text)
          .then(copyText)
          .then(() => setState("done"))
          .catch(() => setState("failed"))
          .finally(() => window.setTimeout(() => setState("idle"), 1500));
      }}
    >
      <Glyph name={look.icon} className={`size-3.5 ${look.className}`} />
      {children}
    </Button>
  );
}

export function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      title="Close (Esc)"
      aria-label="Close"
      onClick={onClick}
      className="rounded p-1 text-muted transition-colors duration-(--dur-fast) hover:bg-hover hover:text-fg"
    >
      <Glyph name="x" className="size-4" />
    </button>
  );
}

/** A small ×: clears a filter or removes an item from a list. */
export function ClearButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="shrink-0 rounded text-muted transition-colors duration-(--dur-fast) hover:text-danger"
    >
      <Glyph name="x" className="size-3" />
    </button>
  );
}

/** A single-value slider; the track fills with the accent up to the thumb (see index.css). */
export function Slider({
  value,
  min,
  max,
  step,
  label,
  onChange,
  className = "",
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  label: string;
  onChange: (value: number) => void;
  className?: string;
}) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      aria-label={label}
      onChange={(e) => onChange(Number(e.target.value))}
      className={className}
      style={{ "--fill": `${fractionOf(value, min, max) * 100}%` } as CSSProperties}
    />
  );
}

/** A value that adds itself as a filter when clicked. */
export function FilterLink({
  children,
  onClick,
  title = "Add as filter",
}: {
  children: ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  if (!onClick) return <span className="break-words">{children}</span>;
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="text-left break-words hover:text-link hover:underline"
    >
      {children}
    </button>
  );
}

/** A model family's colour swatch (see --family-* in theme.css). */
export function FamilyDot({
  family,
  large = false,
  title,
}: {
  family: string | null | undefined;
  large?: boolean;
  title?: string;
}) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full ${large ? "size-2.5" : "size-2"}`}
      style={{ background: familyColor(family) }}
      title={title}
    />
  );
}

/** A thumbnail filling its box; `fallback` stands in when there is none or it fails to load. */
export function Thumbnail({
  hash,
  fallback = null,
  draggable,
  fit = "contain",
}: {
  hash: string | null | undefined;
  fallback?: ReactNode;
  draggable?: boolean;
  fit?: "contain" | "cover";
}) {
  const [failed, onError] = useThumbnailFailure();
  // Fades in once decoded rather than painting in strips; keyed by hash for reused elements.
  const [loaded, setLoaded] = useState<string | null>(null);
  if (!hash || failed) return fallback;
  return (
    <img
      src={thumbUrl(hash)}
      loading="lazy"
      decoding="async"
      draggable={draggable}
      onError={onError}
      onLoad={() => setLoaded(hash)}
      alt=""
      className={`h-full w-full transition-opacity duration-(--dur) ease-snappy ${
        loaded === hash ? "" : "opacity-0"
      } ${fit === "cover" ? "object-cover" : "object-contain"}`}
    />
  );
}

/** A thumbnail in a clickable box; `size` is a Tailwind box class such as "h-16 w-16". */
export function ThumbButton({
  hash,
  size,
  selected = false,
  onClick,
  title,
  disabled,
}: {
  hash: string | null | undefined;
  size: string;
  selected?: boolean;
  onClick?: () => void;
  title?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled ?? !onClick}
      title={title}
      className={`${size} shrink-0 overflow-hidden rounded bg-subtle disabled:cursor-default ${
        selected ? "outline-2 outline-accent" : ""
      }`}
    >
      <Thumbnail hash={hash} />
    </button>
  );
}

export function Message({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-muted">{children}</div>;
}

/** The uppercase caption of a sidebar section, with an optional control on the right. */
export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-1 flex min-h-5 items-center justify-between gap-2">
      <span className="text-xs font-semibold tracking-wide text-muted uppercase">{children}</span>
      {right}
    </div>
  );
}

/** The small caption above a block of panel or detail content. */
export function Heading({ children }: { children: ReactNode }) {
  return <div className="mb-0.5 text-xs font-semibold text-muted">{children}</div>;
}

const BUTTON =
  "rounded border px-2 py-0.5 text-xs transition-colors duration-(--dur-fast) active:translate-y-px";
/** A link styled as an outlined `Button`. */
export const LINK_BUTTON = `${BUTTON} border-control hover:bg-hover`;
const FILLED = `${BUTTON} font-medium text-on-primary disabled:opacity-40`;
/** A filled confirm button. */
export const PRIMARY = `${FILLED} border-primary bg-primary hover:bg-primary-hover`;
/** A filled delete button. */
export const DESTRUCTIVE = `${FILLED} border-destructive bg-destructive hover:bg-destructive-hover`;
/** Text inputs and selects, which mark focus with their border; add size and spacing. */
export const FIELD =
  "rounded border border-control bg-transparent text-fg outline-none transition-colors duration-(--dur-fast) focus:border-accent";
export const th = "px-1.5 py-1 text-left font-medium text-muted";
export const td = "px-1.5 py-1 align-top";
