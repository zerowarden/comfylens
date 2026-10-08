import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, WARMING_TEXT } from "./client";

const respond = (status: number, body: string) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { status, statusText: "Nope" })),
  );

afterEach(() => vi.unstubAllGlobals());

describe("error responses", () => {
  it("read the error envelope", async () => {
    respond(409, JSON.stringify({ error: { code: "name_taken", message: "taken" } }));
    await expect(api.library()).rejects.toMatchObject({ status: 409, code: "name_taken" });
  });

  it("mark a warming prompt analysis", async () => {
    respond(503, JSON.stringify({ warming: true }));
    const error = await api.library().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ warming: true, message: WARMING_TEXT });
  });

  it("fall back to the status text without a JSON body", async () => {
    respond(502, "<html>bad gateway</html>");
    await expect(api.library()).rejects.toMatchObject({ code: "http", message: "502 Nope" });
    respond(500, "null");
    await expect(api.library()).rejects.toMatchObject({ code: "http" });
  });
});
