import { memo, type MouseEvent } from "react";

import type { ImageItem } from "../api/types";
import { fmtDateTime } from "../lib/format";
import { Glyph } from "./icons";
import { Thumbnail } from "./ui";

interface TileProps {
  id: number;
  item: ImageItem | undefined; // undefined while its page loads
  size: number;
  selected: boolean;
  onClick: (id: number, event: MouseEvent) => void;
  onOpen: (id: number) => void;
  onContextMenu: (id: number, event: MouseEvent) => void;
}

function Tile({ id, item, size, selected, onClick, onOpen, onContextMenu }: TileProps) {
  return (
    <div
      data-tile={id}
      onClick={(e) => onClick(id, e)}
      onContextMenu={(e) => onContextMenu(id, e)}
      title={item && tooltip(item)}
      className={`group relative cursor-pointer overflow-hidden rounded bg-subtle ${
        selected ? "outline-3 outline-accent" : "hover:outline-1 hover:outline-faint"
      }`}
      style={{ width: size, height: size }}
    >
      {item && <TileContent item={item} />}
      {/* The only way into the detail view: a click elsewhere on the tile selects it. Hidden
          until the thumbnail is hovered, and only the icon itself responds to presses. */}
      <button
        type="button"
        title="Open image"
        aria-label="Open image"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          onOpen(id);
        }}
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full bg-overlay/60 p-2 text-on-overlay opacity-0 shadow transition-opacity duration-(--dur-fast) group-hover:pointer-events-auto group-hover:opacity-60 group-hover:hover:opacity-90 focus-visible:pointer-events-auto focus-visible:opacity-90"
      >
        <Glyph name="zoomIn" className="size-5" />
      </button>
    </div>
  );
}

const tooltip = (item: ImageItem) =>
  [item.rel_path, fmtDateTime(item.generated_at), item.tags.join(", ")].filter(Boolean).join("\n");

/** The thumbnail with its badges: saved and suspect timestamp at the top, tagged at the bottom. */
function TileContent({ item }: { item: ImageItem }) {
  return (
    <>
      <Thumbnail
        hash={item.content_hash}
        draggable={false}
        fallback={
          <div className="flex h-full w-full items-center justify-center text-xs text-muted">
            no thumbnail
          </div>
        }
      />
      <div className="pointer-events-none absolute inset-x-1 top-1 flex justify-end gap-1">
        {item.saved && (
          <span
            className="rounded bg-primary/90 p-0.5 text-on-primary"
            title="In your prompt collection"
          >
            <Glyph name="bookmark" label="Saved" className="size-3" />
          </span>
        )}
        {item.timestamp_suspect && (
          <span
            className="rounded bg-warning/90 px-1 text-[10px] text-on-warning"
            title="Suspect timestamp"
          >
            ⏱
          </span>
        )}
      </div>
      {item.tags.length > 0 && (
        <Glyph
          name="tag"
          label="Tagged"
          className="pointer-events-none absolute right-1 bottom-1 size-4 text-on-overlay drop-shadow"
        />
      )}
    </>
  );
}

export default memo(Tile);
