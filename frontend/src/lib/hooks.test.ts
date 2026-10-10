import { afterEach, describe, expect, it, vi } from "vitest";

import { copyImage, copyText } from "./hooks";

/** jsdom's navigator has no clipboard; give each test the one it needs. */
function withClipboard(clipboard: unknown) {
  Object.defineProperty(window.navigator, "clipboard", { value: clipboard, configurable: true });
}

function withExecCommand(result: boolean) {
  const exec = vi.fn().mockReturnValue(result);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  return exec;
}

/** A fetch response whose blob resolves to `blob`. */
const imageResponse = (blob: Blob) =>
  ({ ok: true, status: 200, blob: () => Promise.resolve(blob) }) as unknown as Response;

/** jsdom has no image decoding; give the copy fallback what it needs. */
function withImageDecode() {
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    value: vi.fn().mockResolvedValue(undefined),
    configurable: true,
  });
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

describe("copyImage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("writes a PNG through the Clipboard API", async () => {
    const png = new Blob(["png"], { type: "image/png" });
    const fetchMock = vi.fn().mockResolvedValue(imageResponse(png));
    vi.stubGlobal("fetch", fetchMock);
    const write = vi.fn().mockResolvedValue(undefined);
    withClipboard({ write });
    const ClipboardItem = vi.fn();
    vi.stubGlobal("ClipboardItem", ClipboardItem);

    await copyImage("/api/images/1/file");
    expect(fetchMock).toHaveBeenCalledWith("/api/images/1/file");
    expect(ClipboardItem).toHaveBeenCalledWith({ "image/png": png });
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("converts other formats to PNG for the clipboard", async () => {
    const jpeg = new Blob(["jpeg"], { type: "image/jpeg" });
    const png = new Blob(["png"], { type: "image/png" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(imageResponse(jpeg)));
    const write = vi.fn().mockResolvedValue(undefined);
    withClipboard({ write });
    const ClipboardItem = vi.fn();
    vi.stubGlobal("ClipboardItem", ClipboardItem);
    const close = vi.fn();
    const bitmap = { width: 4, height: 2, close };
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bitmap));
    const drawImage = vi.fn();
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      value: vi.fn(() => ({ drawImage })),
      configurable: true,
    });
    const toBlob = vi.fn((callback: BlobCallback) => callback(png));
    Object.defineProperty(HTMLCanvasElement.prototype, "toBlob", {
      value: toBlob,
      configurable: true,
    });

    await copyImage("/api/images/1/file");
    expect(drawImage).toHaveBeenCalledWith(bitmap, 0, 0);
    expect(toBlob).toHaveBeenCalledWith(expect.any(Function), "image/png");
    expect(ClipboardItem).toHaveBeenCalledWith({ "image/png": png });
    expect(close).toHaveBeenCalled();
  });

  it("falls back to execCommand on a plain-HTTP origin without the Clipboard API", async () => {
    const png = new Blob(["png"], { type: "image/png" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(imageResponse(png)));
    withClipboard(undefined);
    withImageDecode();
    const exec = withExecCommand(true);
    const createObjectURL = vi.fn(() => "blob:image");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    await copyImage("/api/images/1/file");
    expect(exec).toHaveBeenCalledWith("copy");
    expect(createObjectURL).toHaveBeenCalledWith(png);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:image");
    expect(document.querySelector("div[contenteditable]")).toBeNull(); // the host is cleaned up
  });

  it("reports a failure when neither path can copy", async () => {
    const png = new Blob(["png"], { type: "image/png" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(imageResponse(png)));
    withClipboard(undefined);
    withImageDecode();
    withExecCommand(false);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:image"),
      revokeObjectURL: vi.fn(),
    });

    await expect(copyImage("/api/images/1/file")).rejects.toThrow(
      "the browser blocked the clipboard",
    );
  });

  it("reports an image that cannot be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 } as unknown as Response),
    );
    await expect(copyImage("/api/images/1/file")).rejects.toThrow(
      "the image could not be read (404)",
    );
  });
});
