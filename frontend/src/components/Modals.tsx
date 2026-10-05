import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { keepKeys } from "../lib/hooks";
import { CloseButton, CopyButton } from "./ui";

/**
 * A full-screen dialog over a blurred backdrop, as the image, saved prompt and compare views use.
 * Clicking the backdrop closes it; each caller handles its own keys, since what Escape and the
 * arrows do depends on what is stacked above it.
 */
export function ViewerModal({
  label,
  onClose,
  layer,
  column = false,
  children,
}: {
  label?: string;
  onClose: () => void;
  /** Stacking: the saved prompt view sits below the image view, which can open on top of it. */
  layer: "z-40" | "z-50";
  /** Stack the contents vertically instead of side by side. */
  column?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`fixed inset-0 ${layer} flex items-center justify-center bg-scrim/50 backdrop-blur-md`}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={`flex h-[90vh] w-[90vw] overflow-hidden rounded-lg bg-canvas shadow-2xl ${
          column ? "flex-col" : ""
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

/** A viewer's title row; `onClose` adds the close button at its end. */
export function ViewerHeader({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return (
    <div className="flex items-center gap-2 border-b border-line px-3 py-2">
      {children}
      <CloseButton onClick={onClose} />
    </div>
  );
}

/** The details column beside a viewer's image: a fixed header over a scrolling body. */
export function ViewerSidebar({ header, children }: { header: ReactNode; children: ReactNode }) {
  return (
    <div className="flex w-[460px] shrink-0 flex-col border-l border-line">
      {header}
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

/** An image fitted to its box; a click toggles 1:1 size, scrolling when it overflows. */
export function ZoomableImage({
  src,
  className,
  onContextMenu,
}: {
  src: string;
  className: string;
  onContextMenu?: (e: React.MouseEvent) => void;
}) {
  const [actualSize, setActualSize] = useState(false);
  return (
    <div
      className={`flex ${className} ${actualSize ? "overflow-auto" : "items-center justify-center overflow-hidden"}`}
      onClick={() => setActualSize(!actualSize)}
      onContextMenu={onContextMenu}
      title={actualSize ? "Click to fit" : "Click for 1:1"}
    >
      <img
        key={src}
        src={src}
        alt=""
        className={
          actualSize
            ? "max-w-none cursor-zoom-out"
            : "max-h-full max-w-full cursor-zoom-in object-contain"
        }
      />
    </div>
  );
}

/** A prompt with its label and a copy button; an empty prompt reads "(empty)". */
export function PromptBox({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-muted">{label}</span>
        <CopyButton label={`Copy ${label.toLowerCase()}`} text={text} />
      </div>
      <pre className="rounded bg-subtle p-2 font-sans text-xs break-words whitespace-pre-wrap">
        {text || "(empty)"}
      </pre>
    </div>
  );
}

/** Copy buttons for the ComfyUI prompt and workflow graphs, fetched only when clicked. */
export function GraphCopyButtons({
  load,
}: {
  load: () => Promise<{ prompt: unknown; workflow: unknown }>;
}) {
  return (
    <>
      <CopyButton
        label="Copy prompt JSON"
        text={async () => JSON.stringify((await load()).prompt, null, 2)}
      >
        Prompt JSON
      </CopyButton>
      <CopyButton
        label="Copy workflow JSON"
        text={async () => JSON.stringify((await load()).workflow, null, 2)}
      >
        Workflow JSON
      </CopyButton>
    </>
  );
}

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
