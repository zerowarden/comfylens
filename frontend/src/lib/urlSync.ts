import { useCollection } from "../state/collection";
import { toSearch, useFilters } from "../state/filters";
import { useUi } from "../state/ui";
import { viewHash } from "./viewHash";

/**
 * Keep the filters, the view and the open saved prompt in the address bar, so a view survives a
 * reload. One writer for both the query string and the hash: each store's change rebuilds both
 * segments from live state, so the two can never overwrite each other.
 */
export function syncUrl(): () => void {
  const write = () => {
    const { filters, sort } = useFilters.getState();
    const search = toSearch(filters, sort);
    const hash = viewHash({
      view: useUi.getState().view,
      promptId: useCollection.getState().openId,
    });
    const url = `${window.location.pathname}${search ? `?${search}` : ""}${hash}`;
    if (url === `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      return;
    }
    window.history.replaceState(null, "", url);
  };
  const stops = [
    useFilters.subscribe(write),
    useUi.subscribe(write),
    useCollection.subscribe(write),
  ];
  return () => stops.forEach((stop) => stop());
}
