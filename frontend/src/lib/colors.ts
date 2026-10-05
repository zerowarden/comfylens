// A family keeps its colour across the grid, timeline and panel. The colours themselves are the
// --family-* tokens in theme.css; this only picks which one a family gets.
const FAMILY_COLORS = 10; // --family-0 … --family-9
export const NO_METADATA = "(no metadata)";

export function familyColor(family: string | null | undefined): string {
  if (!family || family === NO_METADATA) return "var(--family-none)";
  let hash = 0;
  for (let i = 0; i < family.length; i++) hash = (hash * 31 + family.charCodeAt(i)) >>> 0;
  return `var(--family-${hash % FAMILY_COLORS})`;
}
