/** Side-by-side comparison of two images' normalized settings and LoRA chains. */

import type { DetailLora, DetailStage, ImageDetail } from "../api/types";
import { MISSING, fmtDateTime, fmtNum, text } from "./format";
import { SETTING_LABELS } from "./settings";

export interface FieldRow {
  label: string;
  a: string;
  b: string;
  differs: boolean;
}

export interface FieldValue {
  label: string;
  value: string;
}

function resolution(d: ImageDetail): string {
  const f = d.file;
  if (f.width === null || f.height === null) return MISSING;
  const parts = [`${f.width}×${f.height}`];
  if (f.aspect_label) parts.push(f.aspect_label);
  if (f.megapixels !== null) parts.push(`${fmtNum(f.megapixels)} MP`);
  return parts.join(", ");
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
  const rows: [string, string, string][] = [];
  const count = Math.max(a.stages.length, b.stages.length);
  for (let i = 1; i < count; i++) {
    const sa = a.stages[i];
    const sb = b.stages[i];
    for (const [label, read] of STAGE_FIELDS)
      rows.push([`stage ${i} ${label}`, sa ? read(sa) : MISSING, sb ? read(sb) : MISSING]);
  }
  return rows;
}

export function compareFields(a: ImageDetail, b: ImageDetail): FieldRow[] {
  const rows: [string, string, string][] = [
    ...FIELDS.map(([label, read]): [string, string, string] => [label, read(a), read(b)]),
    ...stageFields(a, b),
  ];
  return rows.map(([label, va, vb]) => ({ label, a: va, b: vb, differs: va !== vb }));
}

export interface LoraRow {
  name: string;
  /** Strength as shown ("0.8", or "0.8 / clip 0.5"); null when the chain lacks this LoRA. */
  a: string | null;
  b: string | null;
  differs: boolean;
}

export interface LoraComparison {
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
export function appliedLoras(d: ImageDetail, stage: number): DetailLora[] {
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
export interface StageChain {
  stages: DetailStage[];
  base_model: string | null;
  loras: DetailLora[];
}

/** Each distinct model chain in stage order; stages with the same model and LoRAs share one. */
export function stageChains(d: ImageDetail): StageChain[] {
  const chains: StageChain[] = [];
  for (const s of d.stages) {
    const same = chains.find(
      (c) => c.base_model === s.base_model && c.stages[0]!.lora_stack_key === s.lora_stack_key,
    );
    if (same) same.stages.push(s);
    else chains.push({ stages: [s], base_model: s.base_model, loras: appliedLoras(d, s.index) });
  }
  return chains;
}

/** Every chain's LoRAs keyed so repeated names stay apart; later chains name their stage. */
function chainOf(d: ImageDetail): [string, DetailLora, string][] {
  const keyed: [string, DetailLora, string][] = [];
  stageChains(d).forEach((chain, i) => {
    const seen = new Map<string, number>();
    for (const l of chain.loras) {
      const n = (seen.get(l.name) ?? 0) + 1;
      seen.set(l.name, n);
      const label = i === 0 ? l.name : `${l.name} (stage ${chain.stages[0]!.index})`;
      keyed.push([`${i}:${l.name}#${n}`, l, label]);
    }
  });
  return keyed;
}

/**
 * The two LoRA chains aligned by name: A's order first, then LoRAs only B applies. A row
 * differs when one side lacks the LoRA or the strengths differ.
 */
export function compareLoras(a: ImageDetail, b: ImageDetail): LoraComparison {
  const chainA = chainOf(a);
  const chainB = new Map(chainOf(b).map(([key, l, label]) => [key, [l, label] as const]));
  const rows: LoraRow[] = [];
  for (const [key, l, label] of chainA) {
    const other = chainB.get(key);
    const sa = strengthLabel(l);
    const sb = other ? strengthLabel(other[0]) : null;
    rows.push({ name: label, a: sa, b: sb, differs: sa !== sb });
    chainB.delete(key);
  }
  for (const [l, label] of chainB.values())
    rows.push({ name: label, a: null, b: strengthLabel(l), differs: true });
  return { chain: rows, unusedA: unusedLoras(a), unusedB: unusedLoras(b) };
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
