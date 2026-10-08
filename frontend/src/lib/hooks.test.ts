import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "./hooks";

/** jsdom's navigator has no clipboard; give each test the one it needs. */
function withClipboard(clipboard: unknown) {
  Object.defineProperty(window.navigator, "clipboard", { value: clipboard, configurable: true });
}

function withExecCommand(result: boolean) {
  const exec = vi.fn().mockReturnValue(result);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  return exec;
}

describe("copyText", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the Clipboard API where it exists", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    withClipboard({ writeText });
    const exec = withExecCommand(true);
    await copyText("hello");
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(exec).not.toHaveBeenCalled();
  });

  it("falls back to execCommand on a plain-HTTP origin without the Clipboard API", async () => {
    withClipboard(undefined);
    const exec = withExecCommand(true);
    await copyText("hello");
    expect(exec).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull(); // the field is cleaned up
  });

  it("falls back when writeText is rejected", async () => {
    withClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    const exec = withExecCommand(true);
    await copyText("hello");
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("reports a failure when neither path can copy", async () => {
    withClipboard(undefined);
    withExecCommand(false);
    await expect(copyText("hello")).rejects.toThrow("Could not copy to the clipboard");
  });
});
