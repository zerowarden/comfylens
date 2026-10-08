import type { NumericStats } from "../../api/types";
import { fmtNum } from "../../lib/format";
import type { ListField } from "../../state/filters";

export function rangeText(s: NumericStats): string {
  return s.min === null ? "—" : `${fmtNum(s.min)}–${fmtNum(s.max)}`;
}

const str = (v: unknown) => (v === null || v === undefined ? "?" : String(v));
const num = (v: unknown) => (typeof v === "number" ? fmtNum(v) : "?");

const FIELD_SEPARATOR = " | ";

/** A configuration's fields in display order: model, LoRA stack, sampler/scheduler, steps, ... */
export function configParts(fields: Record<string, unknown>): string[] {
  const parts = [
    str(fields.base_model),
    str(fields.lora_stack_key),
    `${str(fields.sampler_name)}/${str(fields.scheduler)}`,
    `${num(fields.steps)} steps`,
    `cfg ${num(fields.cfg)}`,
    `denoise ${num(fields.denoise)}`,
  ];
  // Guidance and shift only where the graph sets them.
  const optional = (["guidance", "shift"] as const).flatMap((name) => {
    const value = fields[name];
    return typeof value === "number" ? [`${name} ${fmtNum(value)}`] : [];
  });
  return [...parts, ...optional];
}

export function configText(fields: Record<string, unknown>): string {
  return configParts(fields).join(FIELD_SEPARATOR);
}

/** Categorical values that map onto a filter: clicking one adds it. */
export const FILTERABLE: Partial<Record<string, ListField>> = {
  tags: "tags",
  model_family: "families",
  base_model: "base_models",
  sampler_name: "samplers",
  scheduler: "schedulers",
};
