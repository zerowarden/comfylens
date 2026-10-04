import { describe, expect, it } from "vitest";

import type { DetailGeneration, DetailLora, DetailStage, ImageDetail } from "../api/types";
import { compareFields, compareLoras, comparePair, stageChains } from "./compare";

function generation(over: Partial<DetailGeneration> = {}): DetailGeneration {
  return {
    model_family: "krea-2",
    base_model: "krea2_turbo_fp8_scaled",
    text_encoder: "qwen3vl_4b_fp8_scaled",
    clip_type: "krea2",
    vae: "qwen_image_vae",
    seed: "18446744073709551615",
    steps: 8,
    cfg: 1,
    sampler_name: "euler",
    scheduler: "simple",
    denoise: 1,
    guidance: null,
    shift: null,
    stage_count: 1,
    latent_source: "EmptyLatentImage",
    batch_size: 1,
    positive_prompt: "a red fox",
    negative_prompt: "",
    lora_stack_key: "(none)",
    config_key: null,
    generation_key: null,
    ...over,
  };
}

function stage(index: number, over: Partial<DetailStage> = {}): DetailStage {
  return {
    index,
    node_id: String(3 + index),
    class_type: "KSampler",
    seed: "42",
    steps: 8,
    cfg: 1,
    sampler_name: "euler",
    scheduler: "simple",
    denoise: 1,
    start_step: null,
    end_step: null,
    model_family: "krea-2",
    base_model: "krea2_turbo_fp8_scaled",
    text_encoder: "qwen3vl_4b_fp8_scaled",
    clip_type: "krea2",
    lora_stack_key: "(none)",
    positive_prompt: "a red fox",
    negative_prompt: "",
    guidance: null,
    shift: null,
    latent_source: "EmptyLatentImage",
    ...over,
  };
}

function lora(name: string, over: Partial<DetailLora> = {}): DetailLora {
  return {
    position: 0,
    stage_index: 0,
    node_id: "15",
    entry: "",
    class_type: "LoraLoaderModelOnly",
    name_raw: `${name}.safetensors`,
    name,
    base_name: name,
    step: null,
    strength_model: 0.8,
    strength_clip: null,
    enabled: true,
    reachable: true,
    ...over,
  };
}

function detail(
  over: {
    generation?: DetailGeneration | null;
    stages?: DetailStage[];
    loras?: DetailLora[];
    width?: number;
  } = {},
): ImageDetail {
  const width = over.width ?? 1024;
  return {
    file: {
      id: 1,
      rel_path: "a.png",
      format: "png",
      size: 100,
      width,
      height: 1024,
      megapixels: (width * 1024) / 1e6,
      aspect: width / 1024,
      aspect_label: width === 1024 ? "1:1" : "other",
      content_hash: "0".repeat(32),
      generated_at: 1_790_000_000,
      timestamp_suspect: false,
      status: over.generation === null ? "no_metadata" : "ok",
      error: null,
    },
    generation: over.generation === undefined ? generation() : over.generation,
    stages: over.stages ?? (over.generation === null ? [] : [stage(0)]),
    loras: over.loras ?? [],
    input_images: [],
    nodes: [],
    warnings: [],
  };
}

const differing = (rows: { label: string; differs: boolean }[]) =>
  rows.filter((r) => r.differs).map((r) => r.label);

describe("compareFields", () => {
  it("flags only the fields that differ", () => {
    const a = detail();
    const b = detail({ generation: generation({ steps: 25, cfg: 3.5 }), width: 896 });
    expect(differing(compareFields(a, b))).toEqual(["steps", "cfg", "resolution"]);
    const steps = compareFields(a, b).find((r) => r.label === "steps");
    expect(steps).toEqual({ label: "steps", a: "8", b: "25", differs: true });
  });

  it("shows a dash for every generation field of a file without metadata", () => {
    const rows = compareFields(detail(), detail({ generation: null }));
    const family = rows.find((r) => r.label === "family");
    expect(family).toEqual({ label: "family", a: "krea-2", b: "—", differs: true });
    expect(rows.find((r) => r.label === "status")).toMatchObject({ a: "ok", b: "no_metadata" });
    // Both missing is not a difference.
    expect(rows.find((r) => r.label === "guidance")?.differs).toBe(false);
  });
});

describe("compareFields across stages", () => {
  const refiner = stage(1, {
    model_family: "qwen-image-2.1",
    base_model: "qwen_image_2.1_fp8",
    steps: 25,
    cfg: 2,
    denoise: 0.35,
    lora_stack_key: "photoreal@1.06",
    positive_prompt: "make it a realistic photograph",
  });

  it("adds rows for later stages only", () => {
    const rows = compareFields(detail({ stages: [stage(0), refiner] }), detail());
    expect(rows.filter((r) => r.label.startsWith("stage 0"))).toEqual([]);
    expect(rows.find((r) => r.label === "stage 1 denoise")).toEqual({
      label: "stage 1 denoise",
      a: "0.35",
      b: "—",
      differs: true,
    });
  });

  it("flags a changed later stage", () => {
    const a = detail({ stages: [stage(0), refiner] });
    const b = detail({ stages: [stage(0), { ...refiner, denoise: 0.5 }] });
    expect(differing(compareFields(a, b))).toEqual(["stage 1 denoise"]);
  });
});

describe("stageChains", () => {
  it("shares one chain between stages on the same model and LoRAs", () => {
    const hires = detail({
      stages: [
        stage(0, { lora_stack_key: "style@0.8" }),
        stage(1, { lora_stack_key: "style@0.8" }),
      ],
      loras: [lora("style"), lora("style", { stage_index: 1 })],
    });
    const chains = stageChains(hires);
    expect(chains.map((c) => c.stages.map((s) => s.index))).toEqual([[0, 1]]);
    expect(chains[0]!.loras.map((l) => l.name)).toEqual(["style"]);
  });

  it("gives a pass through another model its own chain", () => {
    const d = detail({
      stages: [stage(0), stage(1, { base_model: "qwen", lora_stack_key: "photoreal@1.06" })],
      loras: [lora("photoreal", { stage_index: 1, strength_model: 1.06 })],
    });
    expect(stageChains(d).map((c) => [c.base_model, c.loras.map((l) => l.name)])).toEqual([
      ["krea2_turbo_fp8_scaled", []],
      ["qwen", ["photoreal"]],
    ]);
  });
});

describe("compareLoras", () => {
  it("aligns chains by name and flags strength changes and one-sided LoRAs", () => {
    const a = detail({
      loras: [lora("style", { position: 0 }), lora("detail", { position: 1, strength_model: 1 })],
    });
    const b = detail({
      loras: [lora("detail", { position: 0, strength_model: 0.5 }), lora("extra", { position: 1 })],
    });
    expect(compareLoras(a, b).chain).toEqual([
      { name: "style", a: "0.8", b: null, differs: true },
      { name: "detail", a: "1", b: "0.5", differs: true },
      { name: "extra", a: null, b: "0.8", differs: true },
    ]);
  });

  it("shows clip strength when it differs from model strength", () => {
    const a = detail({ loras: [lora("x", { strength_clip: 0.5 })] });
    const b = detail({ loras: [lora("x", { strength_clip: 0.5 })] });
    expect(compareLoras(a, b).chain).toEqual([
      { name: "x", a: "0.8 / clip 0.5", b: "0.8 / clip 0.5", differs: false },
    ]);
  });

  it("lists unused LoRAs separately and skips switched-off entries", () => {
    const a = detail({
      loras: [
        lora("used"),
        lora("idle", { reachable: false, stage_index: null, position: null, node_id: "25" }),
        lora("off", { enabled: false, position: null }),
      ],
    });
    const result = compareLoras(a, detail({ generation: null }));
    expect(result.chain).toEqual([{ name: "used", a: "0.8", b: null, differs: true }]);
    expect(result.unusedA.map((l) => l.name)).toEqual(["idle"]);
    expect(result.unusedB).toEqual([]);
  });

  it("names the stage of a later chain's LoRAs", () => {
    const qwen = stage(1, { base_model: "qwen", lora_stack_key: "photoreal@1.06" });
    const a = detail({
      stages: [stage(0), qwen],
      loras: [lora("photoreal", { stage_index: 1, strength_model: 1.06 })],
    });
    expect(compareLoras(a, detail()).chain).toEqual([
      { name: "photoreal (stage 1)", a: "1.06", b: null, differs: true },
    ]);
  });
});

describe("comparePair", () => {
  it("orders the pair as the grid shows it, hidden ids last", () => {
    expect(comparePair(new Set([7, 3]), [9, 7, 5, 3])).toEqual([7, 3]);
    expect(comparePair(new Set([42, 5]), [9, 5])).toEqual([5, 42]);
    expect(comparePair(new Set([42, 41]), [])).toEqual([41, 42]);
  });
});
