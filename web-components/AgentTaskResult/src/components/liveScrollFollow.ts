/** How close to the end of the content still counts as being at it. */
export const BOTTOM_TOLERANCE_PX = 32;

export interface ScrollGeometry {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

/** Pixels of content below the visible area; zero or less when everything is on screen. */
export function distanceFromBottom(geometry: ScrollGeometry): number {
  return geometry.scrollHeight - geometry.scrollTop - geometry.clientHeight;
}

export function isAtBottom(geometry: ScrollGeometry): boolean {
  return distanceFromBottom(geometry) < BOTTOM_TOLERANCE_PX;
}

interface ScrollEventState {
  wasReadingEarlier: boolean;
  previousScrollTop: number;
  scrollTop: number;
  atBottom: boolean;
}

/**
 * Whether the reader has scrolled away from the live end, after a scroll event.
 * Only moving up can start it. Content that grows after the view jumped to the end leaves the view short of the new end without anyone scrolling away, and that must not count as reading earlier.
 */
export function readingEarlierAfterScroll({ wasReadingEarlier, previousScrollTop, scrollTop, atBottom }: ScrollEventState): boolean {
  if (atBottom) return false;
  if (scrollTop < previousScrollTop) return true;
  return wasReadingEarlier;
}

/** Whether new live content is actually out of sight below the fold, the only case where Jump to latest helps. */
export function hasContentBelowFold(geometry: ScrollGeometry): boolean {
  return !isAtBottom(geometry);
}
