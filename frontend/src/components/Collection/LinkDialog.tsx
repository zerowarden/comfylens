import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, thumbUrl } from "../../api/client";
import { linkImages } from "../../lib/collection";
import { fmtInt } from "../../lib/format";
import { useDebounced } from "../../lib/hooks";
import { useCollection } from "../../state/collection";
import { Modal } from "../Modals";
import { FOCUS_FIELD } from "../ui";

function LinkForm({ ids }: { ids: number[] }) {
  const client = useQueryClient();
  const openLinking = useCollection((s) => s.openLinking);
  const [text, setText] = useState("");
  const q = useDebounced(text, 200);
  const list = useQuery({
    queryKey: ["collection", "list", q, null, null],
    queryFn: () => api.collection({ q }),
    placeholderData: keepPreviousData,
  });
  const close = () => openLinking(null);
  const title =
    ids.length === 1
      ? "Add to a saved prompt"
      : `Add ${fmtInt(ids.length)} images to a saved prompt`;
  return (
    <Modal title={title} onClose={close}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search saved prompts"
        autoFocus
        className={`mb-2 block w-full px-2 py-1 text-sm ${FOCUS_FIELD}`}
      />
      <p className="mb-2 text-xs text-muted">
        The images are linked as attempts of the prompt; nothing is copied.
      </p>
      {list.isError && <p className="text-xs text-danger">{list.error.message}</p>}
      {list.data?.items.length === 0 && (
        <p className="py-4 text-center text-xs text-muted">
          {q ? "No saved prompts match." : "The collection is empty. Save a prompt first."}
        </p>
      )}
      <ul className="max-h-80 space-y-0.5 overflow-y-auto">
        {list.data?.items.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => {
                close();
                void linkImages(client, p.id, ids);
              }}
              className="flex w-full items-center gap-2 rounded px-1 py-1 text-left text-sm hover:bg-hover focus:bg-hover focus:outline-none"
            >
              <span className="h-8 w-8 shrink-0 overflow-hidden rounded bg-subtle">
                {p.cover_hash && (
                  <img src={thumbUrl(p.cover_hash)} alt="" className="h-full w-full object-cover" />
                )}
              </span>
              <span className="min-w-0 flex-1 truncate">{p.title}</span>
              {p.attempt_count > 0 && (
                <span className="text-xs text-muted">{fmtInt(p.attempt_count)} attempts</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

/** Pick a saved prompt to link library images to, as attempts. */
export default function LinkDialog() {
  const ids = useCollection((s) => s.linking);
  if (!ids) return null;
  return <LinkForm ids={ids} />;
}
