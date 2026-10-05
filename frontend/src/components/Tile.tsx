import { memo, type MouseEvent } from "react";

import type { ImageItem } from "../api/types";
import { fmtDateTime } from "../lib/format";
import { Glyph } from "./icons";
import { FamilyDot, Thumbnail } from "./ui";

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
      onDoubleClick={() => onOpen(id)}
      onContextMenu={(e) => onContextMenu(id, e)}
      title={item ? `${item.rel_path}\n${fmtDateTime(item.generated_at)}` : undefined}
      className={`relative cursor-pointer overflow-hidden rounded bg-subtle ${
        selected ? "outline-3 outline-accent" : "hover:outline-1 hover:outline-faint"
      }`}
      style={{ width: size, height: size }}
    >
      {item && (
        <Thumbnail
          hash={item.content_hash}
          draggable={false}
          fallback={
            <div className="flex h-full w-full items-center justify-center text-xs text-muted">
              no thumbnail
            </div>
          }
        />
      )}
      {item && (
        <div className="pointer-events-none absolute inset-x-1 top-1 flex items-start gap-1">
          <FamilyDot
            family={item.family}
            large
            className="ring-1 ring-overlay/30"
            title={item.family ?? "no metadata"}
          />
          <span className="flex-1" />
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
      )}
    </div>
  );
}

export default memo(Tile);
