import { useState, type ReactNode } from "react";

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
  className = "",
  children,
}: {
  label?: string;
  onClose: () => void;
  /** Stacking: the saved prompt view sits below the image view, which can open on top of it. */
  layer: "z-40" | "z-50";
  /** Stack the contents vertically instead of side by side. */
  column?: boolean;
  /** Extra classes for the overlay, e.g. its enter or exit animation. */
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`fixed inset-0 ${layer} flex items-center justify-center bg-scrim/50 backdrop-blur-md ${className}`}
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

/**
 * A prompt with its label and a copy button. Nothing at all for a missing prompt; an empty one
 * reads "(empty)" unless `hideEmpty` (the saved-prompt view has nothing to show there).
 */
export function PromptBox({
  label,
  text,
  hideEmpty = false,
}: {
  label: string;
  text: string | null;
  hideEmpty?: boolean;
}) {
  if (text === null || (hideEmpty && text === "")) return null;
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
