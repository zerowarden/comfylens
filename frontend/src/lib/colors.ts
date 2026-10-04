// A fixed categorical palette; a family keeps its colour across the grid, timeline and panel.
const PALETTE = [
  "#4e79a7",
  "#f28e2b",
  "#59a14f",
  "#e15759",
  "#b07aa1",
  "#76b7b2",
  "#edc948",
  "#ff9da7",
  "#9c755f",
  "#bab0ac",
];
export const NO_METADATA = "(no metadata)";

export function familyColor(family: string | null | undefined): string {
  if (!family || family === NO_METADATA) return "#6b7280";
  let hash = 0;
  for (let i = 0; i < family.length; i++) hash = (hash * 31 + family.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? "#6b7280";
}
