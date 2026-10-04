import { describe, expect, it } from "vitest";

import { chainKind } from "./chains";

describe("chainKind", () => {
  it("draws family pipelines with arrows and LoRA stacks with links, per stage too", () => {
    expect(chainKind("family")).toBe("pipeline");
    expect(chainKind("stage 1 family")).toBe("pipeline");
    expect(chainKind("LoRA stack")).toBe("lora");
    expect(chainKind("stage 2 LoRA stack")).toBe("lora");
    expect(chainKind("base model")).toBeNull();
  });
});
