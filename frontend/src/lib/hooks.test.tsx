import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDelayedFlag } from "./hooks";

// Lets React's act() flush effects and updates outside a test framework integration.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let seen: boolean[] = [];
let root: Root;

function Probe({ flag }: { flag: boolean }) {
  seen.push(useDelayedFlag(flag, 300));
  return null;
}

const render = (flag: boolean) => act(() => root.render(<Probe flag={flag} />));
const last = () => seen[seen.length - 1];

describe("useDelayedFlag", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    seen = [];
    root = createRoot(document.createElement("div"));
  });
  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
  });

  it("never shows for a fast refresh", () => {
    render(true);
    act(() => vi.advanceTimersByTime(200));
    render(false);
    act(() => vi.advanceTimersByTime(500));
    expect(seen.every((v) => !v)).toBe(true);
  });

  it("shows after the delay and hides at once", () => {
    render(true);
    expect(last()).toBe(false);
    act(() => vi.advanceTimersByTime(300));
    expect(last()).toBe(true);
    render(false);
    expect(last()).toBe(false);
    render(true); // a new refresh waits for the full delay again
    expect(last()).toBe(false);
  });
});
