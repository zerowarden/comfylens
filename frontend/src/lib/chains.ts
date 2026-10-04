/** Separator the backend uses in stage pipelines and LoRA stack keys. */
export const CHAIN_SEPARATOR = " + ";

export type ChainKind = "pipeline" | "lora";

/** Which chain icon a settings field uses, if it holds a chain key. */
export function chainKind(label: string): ChainKind | null {
  if (/(^|\s)family$/.test(label)) return "pipeline";
  if (/(^|\s)LoRA stack$/.test(label)) return "lora";
  return null;
}
