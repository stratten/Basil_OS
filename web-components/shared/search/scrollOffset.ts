/** Gap left above a jump target so it does not sit flush against the top edge of its scroll container. */
export const SEARCH_JUMP_TOP_OFFSET_PX = 8;

/** The `scrollTop` that brings `element` to the top of `container`, never negative. */
export function scrollOffsetForElement(container: HTMLElement, element: HTMLElement): number {
  const offset = element.getBoundingClientRect().top - container.getBoundingClientRect().top;
  return Math.max(0, container.scrollTop + offset - SEARCH_JUMP_TOP_OFFSET_PX);
}
