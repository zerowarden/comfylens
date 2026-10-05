import { useMemo } from "react";

import type { Scope } from "../api/types";
import { useFilters } from "../state/filters";
import { useSelection } from "../state/selection";
import { useDebounced } from "./hooks";

/**
 * The analysis scope: the selection, or else the filtered set. Debounced 150 ms so a burst of
 * clicks sends one request; `key` goes into every TanStack Query key.
 */
export function useScope(): { scope: Scope; key: string } {
  const filters = useFilters((s) => s.filters);
  const selected = useSelection((s) => s.selected);
  const selection = useMemo(() => [...selected].sort((a, b) => a - b), [selected]);
  const scope = useMemo<Scope>(() => ({ selection, filters }), [selection, filters]);
  const debounced = useDebounced(scope, 150);
  return useMemo(() => ({ scope: debounced, key: JSON.stringify(debounced) }), [debounced]);
}
