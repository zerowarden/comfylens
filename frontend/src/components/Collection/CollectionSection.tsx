import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "../../api/client";
import type { PromptRef } from "../../api/types";
import { linkImages, openSavedPrompt, saveImageToCollection } from "../../lib/collection";
import { useCollection } from "../../state/collection";
import { Glyph } from "../icons";
import { Button, FilterLink } from "../ui";

function Ref({ prompt, extra }: { prompt: PromptRef; extra?: ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <Glyph name="bookmark" className="size-3 text-sky-600" />
      <span className="min-w-0 flex-1 truncate">
        <FilterLink title="Open the saved prompt" onClick={() => openSavedPrompt(prompt.id)}>
          {prompt.title}
        </FilterLink>
      </span>
      {extra}
    </li>
  );
}

/** A library image's place in the collection: the prompts it is saved in or shares text with. */
export default function CollectionSection({ id }: { id: number }) {
  const client = useQueryClient();
  const openLinking = useCollection((s) => s.openLinking);
  const query = useQuery({
    queryKey: ["collection", "for-image", id],
    queryFn: () => api.imageCollection(id),
  });
  const data = query.data;
  return (
    <div className="space-y-1 text-xs">
      <div className="flex items-center gap-2">
        <span className="flex-1 font-semibold text-zinc-500">Collection</span>
        <Button
          className="inline-flex items-center gap-1"
          onClick={() => void saveImageToCollection(id)}
        >
          <Glyph name="bookmarkPlus" className="size-3.5" /> Save to collection
        </Button>
        <Button onClick={() => openLinking([id])}>Add to saved prompt…</Button>
      </div>
      {query.isError && <div className="text-zinc-500">{query.error.message}</div>}
      {data && data.linked.length > 0 && (
        <div>
          <div className="text-zinc-500">Saved in</div>
          <ul>
            {data.linked.map((p) => (
              <Ref
                key={p.id}
                prompt={p}
                extra={
                  <span className="text-zinc-500">
                    {p.role === "reference" ? "reference" : "attempt"}
                  </span>
                }
              />
            ))}
          </ul>
        </div>
      )}
      {data && data.matching.length > 0 && (
        <div>
          <div className="text-zinc-500">Same prompt as</div>
          <ul>
            {data.matching.map((p) => (
              <Ref
                key={p.id}
                prompt={p}
                extra={
                  <Button onClick={() => void linkImages(client, p.id, [id])}>
                    Link as attempt
                  </Button>
                }
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
