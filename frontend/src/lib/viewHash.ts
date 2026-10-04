/** Which top-level view is shown, kept in the URL hash: "#collection" or "#collection/12". */
export type View = "library" | "collection";

export interface ViewState {
  view: View;
  /** The saved prompt open in the collection view. */
  promptId: number | null;
}

export function parseViewHash(hash: string): ViewState {
  const match = /^#?collection(?:\/(\d+))?$/.exec(hash);
  if (!match) return { view: "library", promptId: null };
  const id = match[1] ? Number(match[1]) : null;
  return { view: "collection", promptId: id !== null && id > 0 ? id : null };
}

export function viewHash({ view, promptId }: ViewState): string {
  if (view === "library") return "";
  return promptId === null ? "#collection" : `#collection/${promptId}`;
}
