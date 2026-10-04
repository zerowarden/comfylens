import type { NumericStats } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import type { ListField } from "../../state/filters";

export function modeText(s: NumericStats): string {
  if (s.mode.length === 0) return s.mode_note ? `— (${s.mode_note})` : "—";
  const values = s.mode.map(fmtNum).join(", ");
  return `${values} (${fmtPct(s.mode_share)})${s.mode_tied ? " tied" : ""}`;
}

export function rangeText(s: NumericStats): string {
  return s.min === null ? "—" : `${fmtNum(s.min)}–${fmtNum(s.max)}`;
}

const str = (v: unknown) => (v === null || v === undefined ? "?" : String(v));
const num = (v: unknown) => (typeof v === "number" ? fmtNum(v) : "?");

export const FIELD_SEPARATOR = " | ";

/** A configuration's fields in display order: model, LoRA stack, sampler/scheduler, steps, ... */
export function configParts(fields: Record<string, unknown>, withFamily: boolean): string[] {
  const parts = [
    ...(withFamily ? [str(fields.model_family)] : []),
    str(fields.base_model),
    str(fields.lora_stack_key),
    `${str(fields.sampler_name)}/${str(fields.scheduler)}`,
    `${num(fields.steps)} steps`,
    `cfg ${num(fields.cfg)}`,
    `denoise ${num(fields.denoise)}`,
  ];
  if (typeof fields.guidance === "number") parts.push(`guidance ${fmtNum(fields.guidance)}`);
  if (typeof fields.shift === "number") parts.push(`shift ${fmtNum(fields.shift)}`);
  return parts;
}

export function configText(fields: Record<string, unknown>, withFamily: boolean): string {
  return configParts(fields, withFamily).join(FIELD_SEPARATOR);
}

/** Categorical values that map onto a filter: clicking one adds it. */
export const FILTERABLE: Partial<Record<string, ListField>> = {
  model_family: "families",
  base_model: "base_models",
  sampler_name: "samplers",
  scheduler: "schedulers",
};
