export type VerticalBlockAlignment = 'nearest' | 'end';

interface ScrollVerticallyOptions {
  block: VerticalBlockAlignment;
  behavior?: ScrollBehavior;
}

/** The closest ancestor that scrolls vertically on its own and currently has overflow to scroll. */
function nearestVerticalScroller(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) return node;
  }
  return null;
}

/**
 * Reveals an element by scrolling only its nearest vertical scroller.
 *
 * `Element.scrollIntoView` also scrolls horizontally, and it scrolls every ancestor that can scroll, including `overflow: hidden` ones. When the target sits outside the window, such as inside a rail that is still animating open, that leaves the whole result surface offset by a few pixels, which pushes row text against the left edge. This helper never changes `scrollLeft` and never touches an ancestor other than the scroller.
 */
export function scrollVerticallyIntoView(element: HTMLElement, { block, behavior = 'auto' }: ScrollVerticallyOptions): void {
  const scroller = nearestVerticalScroller(element);
  if (!scroller) return;
  const elementRect = element.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();

  let delta = 0;
  if (block === 'end') {
    delta = elementRect.bottom - scrollerRect.bottom;
  } else if (elementRect.top < scrollerRect.top || elementRect.height > scrollerRect.height) {
    delta = elementRect.top - scrollerRect.top;
  } else if (elementRect.bottom > scrollerRect.bottom) {
    delta = elementRect.bottom - scrollerRect.bottom;
  }
  if (delta === 0) return;

  const top = scroller.scrollTop + delta;
  if (typeof scroller.scrollTo === 'function') {
    scroller.scrollTo({ top, behavior });
  } else {
    scroller.scrollTop = top;
  }
}
