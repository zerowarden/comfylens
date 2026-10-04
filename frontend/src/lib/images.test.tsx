import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { LibraryInfo } from "../api/types";
import { useThumbnailFailure } from "./images";

// Lets React's act() flush effects and updates outside a test framework integration.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let client: QueryClient;
let root: Root;
let seen: ReturnType<typeof useThumbnailFailure>[] = [];

function Probe() {
  seen.push(useThumbnailFailure());
  return null;
}

const failed = () => seen.at(-1)?.[0];
const failToLoad = () => act(() => seen.at(-1)?.[1]());

// React Query notifies observers in a setTimeout(0) batch, so the update waits for it.
const serveSnapshot = (builtAt: number) =>
  act(async () => {
    client.setQueryData(["library"], { snapshot_built_at: builtAt } as LibraryInfo);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

describe("useThumbnailFailure", () => {
  beforeEach(async () => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seen = [];
    await serveSnapshot(1);
    root = createRoot(document.createElement("div"));
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <Probe />
        </QueryClientProvider>,
      ),
    );
  });
  afterEach(() => act(() => root.unmount()));

  it("keeps a failure until the next index run's snapshot, then retries", async () => {
    expect(failed()).toBe(false);
    failToLoad();
    expect(failed()).toBe(true);
    await serveSnapshot(1); // a refetch without a new run
    expect(failed()).toBe(true);
    await serveSnapshot(2);
    expect(failed()).toBe(false);
  });

  it("fails again when the retry fails", async () => {
    failToLoad();
    await serveSnapshot(2);
    failToLoad();
    expect(failed()).toBe(true);
  });
});
