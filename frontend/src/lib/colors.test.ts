import { describe, expect, it } from "vitest";

import { familyColor, NO_METADATA } from "./colors";

describe("familyColor", () => {
  it.each([
    { family: "flux", token: "var(--family-7)" },
    { family: "qwen-image-2.1", token: "var(--family-3)" },
    { family: "krea-2", token: "var(--family-4)" },
  ])(
    "gives $family the same palette slot as before the palette moved to CSS",
    ({ family, token }) => {
      expect(familyColor(family)).toBe(token);
    },
  );

  it.each([null, undefined, "", NO_METADATA])("greys out a missing family (%j)", (family) => {
    expect(familyColor(family)).toBe("var(--family-none)");
  });
});
