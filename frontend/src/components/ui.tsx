import { useState, type ReactNode } from "react";

import { copyText } from "../lib/hooks";
import { Glyph } from "./icons";

export function Button({
  children,
  onClick,
  active = false,
  disabled = false,
  title,
  ariaLabel,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
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
      className={`rounded border px-2 py-0.5 text-xs transition-colors disabled:opacity-40 ${
        active
          ? "border-sky-500 bg-sky-500/15 text-sky-700 dark:text-sky-300"
          : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
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
    <div className="inline-flex overflow-hidden rounded border border-zinc-300 dark:border-zinc-700">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`px-2 py-0.5 text-xs ${
            o.value === value
              ? "bg-sky-500/20 text-sky-700 dark:text-sky-300"
              : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
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
    <section className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex flex-1 items-center gap-2 text-left font-medium"
        >
          <Glyph
            name="chevronRight"
            className={`size-3.5 text-zinc-500 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
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

export function ShareBar({ share }: { share: number }) {
  return (
    <div className="h-1.5 w-full rounded bg-zinc-200 dark:bg-zinc-800">
      <div
        className="h-1.5 rounded bg-sky-500"
        style={{ width: `${Math.min(100, share * 100)}%` }}
      />
    </div>
  );
}

const COPY_STATE = {
  idle: { icon: "copy", suffix: "", className: "" },
  done: { icon: "check", suffix: ": copied", className: "text-emerald-600 dark:text-emerald-400" },
  failed: { icon: "circleAlert", suffix: ": failed", className: "text-red-600 dark:text-red-400" },
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
      className="rounded p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
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
      className="text-left break-words hover:text-sky-600 hover:underline dark:hover:text-sky-400"
    >
      {children}
    </button>
  );
}

export function Message({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-zinc-500">{children}</div>;
}

export const th = "px-1.5 py-1 text-left font-medium text-zinc-500";
export const td = "px-1.5 py-1 align-top";
