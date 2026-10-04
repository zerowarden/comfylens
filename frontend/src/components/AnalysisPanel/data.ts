import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../../api/client";
import type { PromptSide, Section } from "../../api/types";
import { useScope } from "../../lib/scope";

const ALL: Section[] = ["numeric", "categorical", "seeds", "loras", "stacks", "configs"];

/** Statistics for the current scope; `lora_key: base_name` is fetched only for the LoRA tab. */
export function useStats(loraKey: "name" | "base_name" = "name", enabled = true) {
  const { scope, key } = useScope();
  const sections: Section[] = loraKey === "name" ? ALL : ["loras", "stacks"];
  return useQuery({
    queryKey: ["stats", key, loraKey],
    queryFn: () => api.stats({ ...scope, sections, lora_key: loraKey }),
    placeholderData: keepPreviousData,
    enabled, // the panel is always mounted; nothing is fetched while it is closed
  });
}

const warmingRetry = {
  // 503 {"warming": true} until prompt frames are built: retry every 2 s.
  retry: (count: number, error: Error) => (error instanceof ApiError && error.warming) || count < 1,
  retryDelay: (_count: number, error: Error) =>
    error instanceof ApiError && error.warming ? 2000 : 1000,
};

export const isWarming = (error: Error | null) => error instanceof ApiError && error.warming;

/** Prompt analysis for the current scope; the Overview and Prompts tabs share its cache. */
export function usePrompts(
  side: PromptSide,
  includeTemplate = false,
  by: "image" | "unique_prompt" = "image",
) {
  const { scope, key } = useScope();
  return useQuery({
    queryKey: ["prompts", key, side, includeTemplate, by],
    queryFn: () => api.prompts({ ...scope, side, include_template: includeTemplate, by }),
    placeholderData: keepPreviousData,
    ...warmingRetry,
  });
}

/** Terms that set the selection apart from the rest of the filtered set. */
export function useDistinctive(side: PromptSide, by: "image" | "unique_prompt") {
  const { scope, key } = useScope();
  return useQuery({
    queryKey: ["distinctive", key, side, by],
    queryFn: () => api.distinctive({ ...scope, side, by }),
    enabled: scope.selection.length > 0,
    // Keep the previous selection's terms on screen while the next ones load.
    placeholderData: keepPreviousData,
    ...warmingRetry,
  });
}
