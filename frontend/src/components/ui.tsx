import { useState, type ReactNode } from "react";

import { thumbUrl } from "../api/client";
import { familyColor } from "../lib/colors";
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

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-control">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`px-2 py-0.5 text-xs ${
            o.value === value ? "bg-accent/20 text-accent-text" : "hover:bg-hover"
          }`}
        >
          {o.label}
        </button>
      ))}
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
  // Ease open only on the user's click: a section that mounts open (new scope, new family) must
  // not replay the animation.
  const [clicked, setClicked] = useState(false);
  const open = controlled ?? own;
  const setOpen = (next: boolean) => {
    setClicked(true);
    if (onToggle) onToggle(next);
    else setOwn(next);
  };
  return (
    <section className="border-b border-line">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex flex-1 items-center gap-2 text-left font-medium"
        >
          <Glyph
            name="chevronRight"
            className={`size-3.5 text-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          />
          {title}
        </button>
        {right}
      </div>
      {open && (
        <div className={`px-3 pb-3 ${clicked ? "motion-safe:animate-expand" : ""}`}>{children}</div>
      )}
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
        className={`h-1.5 rounded ${tone === "warning" ? "bg-warning" : "bg-accent"}`}
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
      className="rounded p-1 text-muted hover:bg-hover hover:text-fg"
    >
      <Glyph name="x" className="size-4" />
    </button>
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
  className = "",
  title,
}: {
  family: string | null | undefined;
  large?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full ${large ? "size-2.5" : "size-2"} ${className}`}
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
  if (!hash || failed) return fallback;
  return (
    <img
      src={thumbUrl(hash)}
      loading="lazy"
      decoding="async"
      draggable={draggable}
      onError={onError}
      alt=""
      className={`h-full w-full ${fit === "cover" ? "object-cover" : "object-contain"}`}
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

/** The small caption above a block of panel or detail content. */
export function Heading({ children }: { children: ReactNode }) {
  return <div className="mb-0.5 text-xs font-semibold text-muted">{children}</div>;
}

const BUTTON = "rounded border px-2 py-0.5 text-xs transition-colors";
/** A link styled as an outlined `Button`. */
export const LINK_BUTTON = `${BUTTON} border-control hover:bg-hover`;
const FILLED = `${BUTTON} font-medium text-on-primary disabled:opacity-40`;
/** A filled confirm button. */
export const PRIMARY = `${FILLED} border-primary bg-primary hover:bg-primary-hover`;
/** A filled delete button. */
export const DESTRUCTIVE = `${FILLED} border-destructive bg-destructive hover:bg-destructive-hover`;
/** Text inputs and selects; add size and spacing. */
export const FIELD = "rounded border border-control bg-transparent";
/** A form field that highlights its border while focused. */
export const FOCUS_FIELD = `${FIELD} text-fg outline-none focus:border-accent`;
export const th = "px-1.5 py-1 text-left font-medium text-muted";
export const td = "px-1.5 py-1 align-top";
