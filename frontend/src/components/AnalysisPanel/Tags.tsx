import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";

import { api } from "../../api/client";
import type { StatsResponse } from "../../api/types";
import { tagImages } from "../../lib/fileActions";
import { splitTags, tagProblem } from "../../lib/files";
import { fmtInt, isSingleSelection } from "../../lib/format";
import { useImageOrder } from "../../lib/images";
import { useSelection } from "../../state/selection";
import Autocomplete from "../Autocomplete";
import { Heading, PRIMARY, FIELD } from "../ui";
import { CategoricalField } from "./Categorical";
import FamilySections from "./FamilySections";

/** A field that writes each tag it is given to every image in scope. */
function AddTags({
  ids,
  target,
  existing,
}: {
  ids: number[];
  /** "selected" or "filtered": whose tags these are, for the note under the field. */
  target: string;
  existing: ReadonlySet<string>;
}) {
  const client = useQueryClient();
  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const [text, setText] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const exclude = useMemo(() => new Set([...existing, ...added]), [existing, added]);
  const typed = splitTags(text);
  const problem = typed.map(tagProblem).find(Boolean);
  const count = ids.length > 0 ? ` (${fmtInt(ids.length)})` : "…";

  const add = (values: string[]) => {
    setText("");
    if (values.length === 0 || ids.length === 0) return;
    setAdded((a) => [...new Set([...a, ...values])]);
    void tagImages(client, ids, values, []);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!problem) add(typed);
  };

  return (
    <div className="space-y-1.5 border-b border-line px-3 py-2">
      <Heading>Add tags</Heading>
      <form onSubmit={submit} className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Autocomplete
            value={text}
            onChange={setText}
            onPick={(tag) => add([tag])}
            options={facets.data?.tags}
            exclude={exclude}
            placeholder="Add tags, separated by commas"
            aria-invalid={problem !== undefined}
            className={`block w-full px-2 py-1 text-xs ${FIELD}`}
          />
        </div>
        <button
          type="submit"
          disabled={typed.length === 0 || Boolean(problem) || ids.length === 0}
          className={PRIMARY}
        >
          Add
        </button>
      </form>
      {problem && <p className="text-xs text-danger">{problem}</p>}
      <p className="text-xs text-muted">
        New tags go on the {target} images{count}. They are written into the image files, where
        other photo tools see them as keywords.
      </p>
    </div>
  );
}

/** The tags of the scope, and a field that writes new ones to every image in it. */
export default function Tags({ data }: { data: StatsResponse }) {
  const selection = useSelection((s) => s.selected);
  const { order } = useImageOrder();
  const single = isSingleSelection(data.scope);
  const ids = useMemo(
    () => (selection.size > 0 ? [...selection].sort((a, b) => a - b) : order),
    [selection, order],
  );
  // Every tag any image in scope holds; suggestions those already have are pointless.
  const existing = useMemo(
    () =>
      new Set(data.groups.flatMap((g) => g.categorical?.tags?.values.map((v) => v.value) ?? [])),
    [data],
  );
  return (
    <div>
      <AddTags
        ids={ids}
        target={selection.size > 0 ? "selected" : "filtered"}
        existing={existing}
      />
      <FamilySections groups={data.groups} count={single ? undefined : (g) => g.images}>
        {(group) => {
          const tags = group.categorical?.tags;
          return tags ? <CategoricalField title="Tags" data={tags} single={single} /> : null;
        }}
      </FamilySections>
    </div>
  );
}
