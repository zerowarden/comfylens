/** Side-by-side comparison of two images' normalized settings and LoRA chains. */

import type { DetailLora, DetailStage, ImageDetail } from "../api/types";
import { MISSING, fmtDateTime, fmtNum, text } from "./format";
import { SETTING_LABELS } from "./settings";

interface FieldRow {
  label: string;
  a: string;
  b: string;
  differs: boolean;
}

interface FieldValue {
  label: string;
  value: string;
}

function resolution(d: ImageDetail): string {
  const f = d.file;
  if (f.width === null || f.height === null) return MISSING;
  const megapixels = f.megapixels !== null && `${fmtNum(f.megapixels)} MP`;
  return [`${f.width}×${f.height}`, f.aspect_label, megapixels].filter(Boolean).join(", ");
}

/** Field label and how to read it; generation fields are MISSING for files without metadata. */
const FIELDS: [string, (d: ImageDetail) => string][] = [
  ["status", (d) => (d.file.error ? `${d.file.status}: ${d.file.error}` : d.file.status)],
  ["family", (d) => text(d.generation?.model_family)],
  [SETTING_LABELS.base_model, (d) => text(d.generation?.base_model)],
  ["text encoder", (d) => text(d.generation?.text_encoder)],
  ["clip type", (d) => text(d.generation?.clip_type)],
  ["vae", (d) => text(d.generation?.vae)],
  [SETTING_LABELS.sampler_name, (d) => text(d.generation?.sampler_name)],
  [SETTING_LABELS.scheduler, (d) => text(d.generation?.scheduler)],
  [SETTING_LABELS.steps, (d) => text(d.generation?.steps)],
  [SETTING_LABELS.cfg, (d) => fmtNum(d.generation?.cfg)],
  [SETTING_LABELS.denoise, (d) => fmtNum(d.generation?.denoise)],
  [SETTING_LABELS.guidance, (d) => fmtNum(d.generation?.guidance)],
  [SETTING_LABELS.shift, (d) => fmtNum(d.generation?.shift)],
  [SETTING_LABELS.seed, (d) => text(d.generation?.seed)],
  ["stages", (d) => text(d.generation?.stage_count)],
  ["latent source", (d) => text(d.generation?.latent_source)],
  ["batch size", (d) => text(d.generation?.batch_size)],
  ["resolution", resolution],
  [
    "generated",
    (d) =>
      (d.file.generated_at === null ? MISSING : fmtDateTime(d.file.generated_at)) +
      (d.file.timestamp_suspect ? " (suspect timestamp)" : ""),
  ],
  ["LoRA stack", (d) => text(d.generation?.lora_stack_key)],
];

/** One row per setting, for the detail view; Compare labels the same rows A and B. */
export function settingsRows(d: ImageDetail): FieldValue[] {
  return FIELDS.map(([label, read]) => ({ label, value: read(d) }));
}

/** What a later stage ran with; the image-level rows already describe the primary stage. */
const STAGE_FIELDS: [string, (s: DetailStage) => string][] = [
  ["family", (s) => s.model_family],
  [SETTING_LABELS.base_model, (s) => text(s.base_model)],
  [SETTING_LABELS.sampler_name, (s) => `${text(s.sampler_name)} / ${text(s.scheduler)}`],
  [SETTING_LABELS.steps, (s) => text(s.steps)],
  [SETTING_LABELS.cfg, (s) => fmtNum(s.cfg)],
  [SETTING_LABELS.denoise, (s) => fmtNum(s.denoise)],
  [SETTING_LABELS.seed, (s) => text(s.seed)],
  ["LoRA stack", (s) => s.lora_stack_key],
  ["prompt", (s) => text(s.positive_prompt)],
];

function stageFields(a: ImageDetail, b: ImageDetail): [string, string, string][] {
  const later = Math.max(a.stages.length, b.stages.length) - 1;
  const readStage = (s: DetailStage | undefined, read: (s: DetailStage) => string) =>
    s ? read(s) : MISSING;
  return Array.from({ length: Math.max(0, later) }, (_, k) => k + 1).flatMap((i) =>
    STAGE_FIELDS.map(([label, read]): [string, string, string] => [
      `stage ${i} ${label}`,
      readStage(a.stages[i], read),
      readStage(b.stages[i], read),
    ]),
  );
}

export function compareFields(a: ImageDetail, b: ImageDetail): FieldRow[] {
  const rows: [string, string, string][] = [
    ...FIELDS.map(([label, read]): [string, string, string] => [label, read(a), read(b)]),
    ...stageFields(a, b),
  ];
  return rows.map(([label, va, vb]) => ({ label, a: va, b: vb, differs: va !== vb }));
}

interface LoraRow {
  name: string;
  /** Strength as shown ("0.8", or "0.8 / clip 0.5"); null when the chain lacks this LoRA. */
  a: string | null;
  b: string | null;
  differs: boolean;
}

interface LoraComparison {
  chain: LoraRow[];
  /** LoRAs loaded but not connected to any sampler, per side. */
  unusedA: DetailLora[];
  unusedB: DetailLora[];
}

/** The strength as both views show it: model, plus clip when they differ. */
export function strengthLabel(l: DetailLora): string {
  const model = fmtNum(l.strength_model);
  const clip = l.strength_clip;
  return clip !== null && clip !== l.strength_model ? `${model} / clip ${fmtNum(clip)}` : model;
}

/** The LoRAs a stage applied: on its model chain and switched on, in chain order. */
function appliedLoras(d: ImageDetail, stage: number): DetailLora[] {
  return d.loras
    .filter((l) => l.stage_index === stage && l.enabled)
    .sort((x, y) => (x.position ?? 0) - (y.position ?? 0));
}

/** LoRAs on some stage's chain but switched off, each once. */
export function disabledLoras(d: ImageDetail): DetailLora[] {
  const seen = new Set<string>();
  return d.loras.filter((l) => {
    const key = `${l.node_id}:${l.entry}`;
    if (!l.reachable || l.enabled || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** LoRAs loaded but not connected to any sampler. */
export function unusedLoras(d: ImageDetail): DetailLora[] {
  return d.loras.filter((l) => !l.reachable);
}

/** One model chain and the stages that ran on it, e.g. both passes of a hires fix. */
interface StageChain {
  stages: DetailStage[];
  base_model: string | null;
  loras: DetailLora[];
}

/** Each distinct model chain in stage order; stages with the same model and LoRAs share one. */
export function stageChains(d: ImageDetail): StageChain[] {
  const byChain = d.stages.reduce((groups, s) => {
    const key = JSON.stringify([s.base_model, s.lora_stack_key]);
    return groups.set(key, [...(groups.get(key) ?? []), s]);
  }, new Map<string, DetailStage[]>());
  return [...byChain.values()].map((stages) => ({
    stages,
    base_model: stages[0]!.base_model,
    loras: appliedLoras(d, stages[0]!.index),
  }));
}

/** Every chain's LoRAs keyed so repeated names stay apart; later chains name their stage. */
function chainOf(d: ImageDetail): [string, DetailLora, string][] {
  return stageChains(d).flatMap((chain, i) =>
    chain.loras.map((l, j): [string, DetailLora, string] => {
      // The nth use of this name in the chain.
      const n = chain.loras.slice(0, j + 1).filter((o) => o.name === l.name).length;
      const label = i === 0 ? l.name : `${l.name} (stage ${chain.stages[0]!.index})`;
      return [`${i}:${l.name}#${n}`, l, label];
    }),
  );
}

/**
 * The two LoRA chains aligned by name: A's order first, then LoRAs only B applies. A row
 * differs when one side lacks the LoRA or the strengths differ.
 */
export function compareLoras(a: ImageDetail, b: ImageDetail): LoraComparison {
  const chainA = chainOf(a);
  const chainB = new Map(chainOf(b).map(([key, l, label]) => [key, [l, label] as const]));
  const keysA = new Set(chainA.map(([key]) => key));
  const inA = chainA.map(([key, l, label]): LoraRow => {
    const other = chainB.get(key);
    const sa = strengthLabel(l);
    const sb = other ? strengthLabel(other[0]) : null;
    return { name: label, a: sa, b: sb, differs: sa !== sb };
  });
  const onlyB = [...chainB]
    .filter(([key]) => !keysA.has(key))
    .map(([, [l, label]]): LoraRow => ({
      name: label,
      a: null,
      b: strengthLabel(l),
      differs: true,
    }));
  return { chain: [...inA, ...onlyB], unusedA: unusedLoras(a), unusedB: unusedLoras(b) };
}

/** The two selected ids for Compare, in grid order; ids hidden by filters go last. */
export function comparePair(
  selected: ReadonlySet<number>,
  order: readonly number[],
): [number, number] {
  const rank = new Map(order.map((id, i) => [id, i]));
  const at = (id: number) => rank.get(id) ?? Number.MAX_SAFE_INTEGER;
  const [a, b] = [...selected].sort((x, y) => at(x) - at(y) || x - y);
  return [a!, b!];
}
