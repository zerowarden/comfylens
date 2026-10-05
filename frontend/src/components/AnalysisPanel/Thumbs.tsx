import { useUi } from "../../state/ui";
import { Thumbnail } from "../ui";

function Thumb({ id, hash }: { id: number; hash: string | undefined }) {
  const openDetail = useUi((s) => s.openDetail);
  return (
    <button
      type="button"
      onClick={() => openDetail(id)}
      title={`Open image ${id}`}
      className="h-12 w-12 shrink-0 overflow-hidden rounded bg-subtle"
    >
      <Thumbnail hash={hash} />
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
