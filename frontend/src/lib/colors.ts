// A family keeps its colour across the grid, timeline and panel. The colours themselves are the
// --family-* tokens in theme.css; this only picks which one a family gets.
const FAMILY_COLORS = 10; // --family-0 … --family-9
export const NO_METADATA = "(no metadata)";

export function familyColor(family: string | null | undefined): string {
  if (!family || family === NO_METADATA) return "var(--family-none)";
  const hash = family.split("").reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 0);
  return `var(--family-${hash % FAMILY_COLORS})`;
}
