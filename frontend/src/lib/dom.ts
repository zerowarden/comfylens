/** Browser-input helpers shared by the grid and the collection views. */

/** The image types the collection accepts, for <input accept> and drop checks. */
export const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";

/** Whether an event target is a text field: shortcuts must not fire while typing. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

/** Whether a drag event carries files. */
export function hasFiles(e: { dataTransfer: DataTransfer | null }): boolean {
  return e.dataTransfer?.types.includes("Files") ?? false;
}
