import { describe, expect, it } from "vitest";

import { configParts } from "./format";

describe("configParts", () => {
  const base = {
    base_model: "flux1-dev",
    lora_stack_key: "(none)",
    sampler_name: "euler",
    scheduler: "simple",
    steps: 20,
    cfg: 1,
    denoise: 1,
  };

  it("adds guidance and shift only where the graph sets them", () => {
    expect(configParts(base)).toHaveLength(6);
    expect(configParts({ ...base, guidance: 3.5, shift: null }).slice(6)).toEqual(["guidance 3.5"]);
    expect(configParts({ ...base, guidance: 3.5, shift: 3 }).slice(6)).toEqual([
      "guidance 3.5",
      "shift 3",
    ]);
  });
});
