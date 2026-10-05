/** Pure draft rules: what a dropped image becomes before anything is saved. */

import type {
  CollectionImage,
  Draft,
  PromptInput,
  PromptSettings,
  SavedPrompt,
} from "../api/types";
import { promptSettingsRows } from "./settings";

/**
 * Several dropped files make one prompt: the first draft with generation metadata (else the
 * first) gives the text and settings, and every image becomes a reference, in drop order.
 */
export function seedDraft(drafts: Draft[]): { draft: Draft; references: CollectionImage[] } | null {
  const first = drafts.find((d) => d.metadata !== "none") ?? drafts[0];
  if (!first) return null;
  const seen = new Set<string>();
  const references: CollectionImage[] = [];
  for (const d of drafts) {
    if (d.original && !seen.has(d.original.content_hash)) {
      seen.add(d.original.content_hash);
      references.push(d.original);
    }
  }
  return { draft: first, references };
}

/** Tags typed as "a, b , a" -> ["a", "b"]; the server normalizes case and spacing again. */
export function parseTags(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const tag = raw.trim().replace(/\s+/g, " ").toLowerCase();
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

export function emptySettings(): PromptSettings {
  return {
    base_model: null,
    seed: null,
    steps: null,
    cfg: null,
    sampler_name: null,
    scheduler: null,
    denoise: null,
    guidance: null,
    shift: null,
    loras: [],
  };
}

/** The editable fields of a saved prompt, as the editor starts with them. */
export function inputOf(prompt: SavedPrompt): PromptInput {
  return {
    title: prompt.title,
    positive: prompt.positive,
    negative: prompt.negative,
    notes: prompt.notes,
    source_url: prompt.source_url,
    model_family: prompt.model_family,
    tags: prompt.tags,
    settings: prompt.settings,
    references: prompt.references.map((r) => r.content_hash),
    attempts: [],
  };
}

export function inputOfDraft(draft: Draft, references: CollectionImage[]): PromptInput {
  return {
    title: draft.title,
    positive: draft.positive,
    negative: draft.negative,
    notes: "",
    source_url: null,
    model_family: draft.model_family,
    tags: [],
    settings: draft.settings,
    references: references.map((r) => r.content_hash),
    attempts: [],
  };
}

/** The editor fields an added image's metadata can fill in. */
export interface DraftFields {
  title: string;
  positive: string;
  negative: string;
  family: string;
  settings: PromptSettings;
}

function settingsEmpty(s: PromptSettings): boolean {
  return s.loras.length === 0 && promptSettingsRows(s).length === 0;
}

/** References with the drafts' images appended, in order, without duplicates. */
export function appendReferences(
  references: CollectionImage[],
  drafts: Draft[],
): CollectionImage[] {
  const out = [...references];
  for (const d of drafts) {
    if (d.original && !out.some((r) => r.content_hash === d.original!.content_hash)) {
      out.push(d.original);
    }
  }
  return out;
}

/**
 * Fill the fields the user left empty from the first added image that carries generation
 * metadata; never overwrite what is already there.
 */
export function fillEmptyFields(fields: DraftFields, drafts: Draft[]): DraftFields {
  const source = drafts.find((d) => d.metadata !== "none");
  if (!source) return fields;
  return {
    title: fields.title.trim() ? fields.title : source.title,
    positive: fields.positive.trim() ? fields.positive : source.positive,
    negative: fields.negative.trim() ? fields.negative : source.negative,
    family: fields.family.trim() ? fields.family : (source.model_family ?? ""),
    settings: settingsEmpty(fields.settings) ? source.settings : fields.settings,
  };
}

/** Image files among dropped or pasted ones. */
export function imageFiles(files: Iterable<File>): File[] {
  return [...files].filter((f) => f.type === "" || f.type.startsWith("image/"));
}
