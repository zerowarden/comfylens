import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Autocomplete from "./Autocomplete";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const OPTIONS = ["fox", "foxglove", "owl"].map((value, i) => ({ value, count: 3 - i }));
let root: Root;
let host: HTMLDivElement;
const picked = vi.fn();
const outer = vi.fn(); // a dialog's own key handler

function Field() {
  const [value, setValue] = useState("");
  return (
    <div onKeyDown={(e) => outer(e.key)}>
      <Autocomplete
        value={value}
        onChange={setValue}
        onPick={(v) => {
          picked(v);
          setValue(v);
        }}
        options={OPTIONS}
      />
    </div>
  );
}

const input = () => host.querySelector("input")!;
const rows = () => [...document.querySelectorAll('[role="option"]')].map((li) => li.textContent);
const highlighted = () => document.querySelector('[aria-selected="true"]')?.textContent;

function type(text: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input(), text);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const press = (key: string) =>
  act(() => input().dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true })));

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root.render(<Field />));
  picked.mockReset();
  outer.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("Autocomplete", () => {
  it("lists matches with their counts as you type, and opens on ArrowDown", () => {
    expect(rows()).toEqual([]);
    type("fo");
    expect(rows()).toEqual(["fox3", "foxglove2"]);
    expect(input().getAttribute("aria-expanded")).toBe("true");
    press("Escape");
    expect(rows()).toEqual([]);
    press("ArrowDown");
    expect(rows()).toEqual(["fox3", "foxglove2"]);
  });

  it("moves the highlight through the rows and back to none, then picks with Enter", () => {
    type("fo");
    press("Enter"); // nothing highlighted: Enter is left to the form
    expect(picked).not.toHaveBeenCalled();
    expect(outer).toHaveBeenCalledWith("Enter");
    press("ArrowDown");
    press("ArrowDown");
    expect(highlighted()).toBe("foxglove2");
    press("ArrowDown");
    expect(highlighted()).toBeUndefined();
    press("ArrowUp");
    expect(highlighted()).toBe("foxglove2");
    press("Enter");
    expect(picked).toHaveBeenCalledWith("foxglove");
    expect(rows()).toEqual([]);
  });

  it("keeps Escape from the dialog around it only while the list is open", () => {
    type("o");
    press("Escape");
    expect(outer).not.toHaveBeenCalled();
    press("Escape");
    expect(outer).toHaveBeenCalledWith("Escape");
  });

  it("picks a row on click without losing focus to it", () => {
    type("ow");
    const row = document.querySelector('[role="option"]')!;
    const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => row.dispatchEvent(down));
    expect(down.defaultPrevented).toBe(true);
    act(() => row.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(picked).toHaveBeenCalledWith("owl");
  });
});
