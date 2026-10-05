import { useUi } from "../../state/ui";
import { ThumbButton } from "../ui";

/** Up to 6 example images; click opens the detail view. */
export default function Thumbs({ ids, hashes }: { ids: number[]; hashes: string[] }) {
  const openDetail = useUi((s) => s.openDetail);
  return (
    <div className="mt-1 flex gap-1">
      {ids.slice(0, 6).map((id, i) => (
        <ThumbButton
          key={id}
          hash={hashes[i]}
          size="h-12 w-12"
          onClick={() => openDetail(id)}
          title={`Open image ${id}`}
        />
      ))}
    </div>
  );
}
