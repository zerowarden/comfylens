import { thumbUrl } from "../../api/client";
import { useThumbnailFailure } from "../../lib/images";
import { useUi } from "../../state/ui";

function Thumb({ id, hash }: { id: number; hash: string | undefined }) {
  const openDetail = useUi((s) => s.openDetail);
  const [failed, onThumbnailError] = useThumbnailFailure();
  return (
    <button
      type="button"
      onClick={() => openDetail(id)}
      title={`Open image ${id}`}
      className="h-12 w-12 shrink-0 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-900"
    >
      {hash && !failed && (
        <img
          src={thumbUrl(hash)}
          loading="lazy"
          alt=""
          onError={onThumbnailError}
          className="h-full w-full object-contain"
        />
      )}
    </button>
  );
}

/** Up to 6 example images; click opens the detail view. */
export default function Thumbs({ ids, hashes }: { ids: number[]; hashes: string[] }) {
  return (
    <div className="mt-1 flex gap-1">
      {ids.slice(0, 6).map((id, i) => (
        <Thumb key={id} id={id} hash={hashes[i]} />
      ))}
    </div>
  );
}
