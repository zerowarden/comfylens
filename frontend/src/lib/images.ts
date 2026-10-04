import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { Filters, Sort } from "../api/types";
import { useFilters } from "../state/filters";

/**
 * One image's full detail; the detail, Compare and rename views share this query and its cache.
 * With `enabled` false it only reads the cache.
 */
export function useImageDetail(id: number, enabled = true) {
  return useQuery({
    queryKey: ["image", id],
    queryFn: () => api.image(id),
    staleTime: Infinity,
    enabled,
  });
}

/** Images per grid page query: ["page", orderKey, page]. */
export const PAGE_SIZE = 500;

/** The cache key part shared by the id list ["ids", key] and its pages ["page", key, page]. */
export function orderKey(filters: Filters, sort: Sort): string {
  return JSON.stringify([filters, sort]);
}

/** Every filtered id in sort order: drives the grid, select-all, shift ranges and detail stepping. */
export function useImageOrder() {
  const filters = useFilters((s) => s.filters);
  const sort = useFilters((s) => s.sort);
  const key = useMemo(() => orderKey(filters, sort), [filters, sort]);
  const query = useQuery({
    queryKey: ["ids", key],
    queryFn: () => api.ids({ filters, sort }),
    placeholderData: keepPreviousData,
  });
  const order = useMemo(() => query.data?.ids ?? [], [query.data]);
  return { order, filters, sort, key, query };
}

/**
 * Whether this thumbnail failed to load, and the `onError` that records it. Index runs write
 * thumbnails, so a failure counts only until the next run's snapshot is served: then the image is
 * requested again, e.g. after Rescan restores a cleared cache. Loaded thumbnails are not touched.
 */
export function useThumbnailFailure(): [failed: boolean, onError: () => void] {
  const { data: builtAt = null } = useQuery({
    queryKey: ["library"],
    queryFn: api.library,
    select: (library) => library.snapshot_built_at,
    staleTime: Infinity, // the top bar refreshes the library; tiles only read it
  });
  const [failedAt, setFailedAt] = useState<number | null | undefined>(undefined);
  return [failedAt === builtAt, () => setFailedAt(builtAt)];
}
