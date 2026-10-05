import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { keepKeys } from "../lib/hooks";

/** A small dialog over the page that keeps keyboard focus inside it until closed. */
export function Modal({
  title,
  onClose,
  children,
  width = "w-[460px]",
  align = "center",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** A Tailwind width class. */
  width?: string;
  /** "top" for a dialog whose height changes while open: it then grows downward only. */
  align?: "center" | "top";
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Close on a click that both starts and ends on the backdrop: a text selection dragged out of
  // the input must not dismiss the dialog.
  const pressedBackdrop = useRef(false);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    keepKeys(e);
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "Tab") {
      const focusable = [
        ...(ref.current?.querySelectorAll<HTMLElement>(
          "input, textarea, select, a[href], button:not(:disabled)",
        ) ?? []),
      ];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
  };

  return (
    <div
      className={`fixed inset-0 z-[70] flex justify-center bg-scrim/40 ${
        align === "top" ? "items-start pt-[5vh]" : "items-center"
      }`}
      onMouseDown={(e) => {
        pressedBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (pressedBackdrop.current && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={`${width} max-h-[90vh] max-w-[90vw] overflow-y-auto rounded-lg bg-surface p-4 shadow-2xl outline-none`}
      >
        <h2 className="mb-3 font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}
