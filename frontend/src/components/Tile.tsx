import { memo, type MouseEvent } from "react";

import { thumbUrl } from "../api/client";
import type { ImageItem } from "../api/types";
import { familyColor } from "../lib/colors";
import { fmtDateTime } from "../lib/format";
import { useThumbnailFailure } from "../lib/images";

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
  const [failed, onThumbnailError] = useThumbnailFailure();
  return (
    <div
      data-tile={id}
      onClick={(e) => onClick(id, e)}
      onDoubleClick={() => onOpen(id)}
      onContextMenu={(e) => onContextMenu(id, e)}
      title={item ? `${item.rel_path}\n${fmtDateTime(item.generated_at)}` : undefined}
      className={`relative cursor-pointer overflow-hidden rounded bg-zinc-100 dark:bg-zinc-900 ${
        selected ? "outline-3 outline-sky-500" : "hover:outline-1 hover:outline-zinc-400"
      }`}
      style={{ width: size, height: size }}
    >
      {item && !failed && item.content_hash && (
        <img
          src={thumbUrl(item.content_hash)}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={onThumbnailError}
          alt=""
          className="h-full w-full object-contain"
        />
      )}
      {item && (failed || !item.content_hash) && (
        <div className="flex h-full w-full items-center justify-center text-xs text-zinc-500">
          no thumbnail
        </div>
      )}
      {item && (
        <div className="pointer-events-none absolute inset-x-1 top-1 flex items-start gap-1">
          <span
            className="h-2.5 w-2.5 rounded-full ring-1 ring-black/30"
            style={{ background: familyColor(item.family) }}
            title={item.family ?? "no metadata"}
          />
          <span className="flex-1" />
          {item.timestamp_suspect && (
            <span
              className="rounded bg-amber-500/90 px-1 text-[10px] text-black"
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
