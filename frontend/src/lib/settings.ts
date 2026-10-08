/** The generation settings every view shows, and their labels. */

import type { PromptSettings, SavedLora } from "../api/types";

export const SETTING_LABELS = {
  base_model: "base model",
  sampler_name: "sampler",
  scheduler: "scheduler",
  steps: "steps",
  cfg: "cfg",
  denoise: "denoise",
  guidance: "guidance",
  shift: "shift",
  seed: "seed",
} as const;

type SettingKey = keyof typeof SETTING_LABELS;

/** In declaration order, so every list presents the settings the same way. */
const SETTING_KEYS = Object.keys(SETTING_LABELS) as SettingKey[];

/** A saved prompt's known settings as label/value rows; unknown ones are left out. */
export function promptSettingsRows(s: PromptSettings): { label: string; value: string }[] {
  return SETTING_KEYS.flatMap((key) => {
    const value = s[key];
    return value === null || value === ""
      ? []
      : [{ label: SETTING_LABELS[key], value: String(value) }];
  });
}

/** "fox 0.8", or "fox 0.8 / 1" when the clip strength differs. */
export function loraText(l: SavedLora): string {
  const model = l.strength_model ?? "?";
  const clip = l.strength_clip !== null && l.strength_clip !== l.strength_model;
  return `${l.name} ${model}${clip ? ` / ${l.strength_clip}` : ""}`;
}
