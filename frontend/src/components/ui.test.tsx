import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Reveal, Segmented, Thumbnail } from "./ui";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("Reveal", () => {
  const render = (open: boolean) =>
    act(() =>
      root.render(
        <Reveal open={open}>
          <p>content</p>
        </Reveal>,
      ),
    );
  const slid = () =>
    act(() => host.firstChild!.dispatchEvent(new Event("transitionend", { bubbles: true })));
  const content = () => host.querySelector("p");

  it("mounts open without sliding, and keeps the content until the slide shut ends", () => {
    render(true);
    expect(content()).not.toBeNull();
    render(false);
    expect(content()).not.toBeNull(); // still sliding shut
    expect((host.firstChild as HTMLElement).hasAttribute("inert")).toBe(true);
    slid();
    expect(content()).toBeNull();
  });

  it("mounts the content as soon as it opens, and clips it only while it moves", () => {
    render(false);
    expect(content()).toBeNull();
    render(true);
    expect(content()?.parentElement?.className).toContain("overflow-hidden");
    slid();
    expect(content()?.parentElement?.className).not.toContain("overflow-hidden");
  });

  it("ignores the end of a transition inside the content", () => {
    render(true);
    render(false);
    act(() => content()!.dispatchEvent(new Event("transitionend", { bubbles: true })));
    expect(content()).not.toBeNull();
  });
});

describe("Segmented", () => {
  it("marks the chosen option as pressed", () => {
    const options = [
      { value: "a", label: "A" },
      { value: "b", label: "B" },
    ];
    act(() => root.render(<Segmented value="b" options={options} onChange={() => {}} />));
    const pressed = [...host.querySelectorAll("button")].map((b) => b.getAttribute("aria-pressed"));
    expect(pressed).toEqual(["false", "true"]);
  });
});

describe("Thumbnail", () => {
  const render = (hash: string) =>
    act(() =>
      root.render(
        <QueryClientProvider client={new QueryClient()}>
          <Thumbnail hash={hash} />
        </QueryClientProvider>,
      ),
    );
  const img = () => host.querySelector("img")!;

  it("fades in once loaded, and again for another image in the same element", () => {
    render("a");
    expect(img().className).toContain("opacity-0");
    act(() => img().dispatchEvent(new Event("load")));
    expect(img().className).not.toContain("opacity-0");
    render("b");
    expect(img().className).toContain("opacity-0");
  });
});
