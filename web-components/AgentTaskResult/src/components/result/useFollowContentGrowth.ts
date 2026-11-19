import { useEffect, type RefObject } from 'react';

interface FollowContentGrowthOptions {
  scrollRef: RefObject<HTMLElement>;
  /** Read at every size change: true while the run is live and the reader has not scrolled away from its end. Must keep the same identity between renders. */
  shouldFollow: () => boolean;
  /** Told after each pin, so the caller's record of the last scroll position matches where the view now is. Must keep the same identity between renders. */
  onPinned: (scrollTop: number) => void;
}

/**
 * Keeps the end of a live thread in view while it grows after the render that added to it.
 *
 * Scrolling in the effect that sees new content only reaches the end of what has been laid out by then. A card that animates open, a reasoning section that fills in, or a turn still loading from the backend keeps growing afterward, and the view is left short of the new end with nothing to scroll it again. Watching the size of the scroller's direct children means each step of that growth is followed, and a child added or removed is picked up through its own observer.
 */
export function useFollowContentGrowth({ scrollRef, shouldFollow, onPinned }: FollowContentGrowthOptions): void {
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || typeof ResizeObserver === 'undefined') return undefined;

    const pin = () => {
      if (!shouldFollow()) return;
      scroller.scrollTop = scroller.scrollHeight;
      onPinned(scroller.scrollTop);
    };

    const resizeObserver = new ResizeObserver(pin);
    const watched = new Set<Element>();
    const watchChildren = () => {
      for (const child of Array.from(scroller.children)) {
        if (watched.has(child)) continue;
        watched.add(child);
        resizeObserver.observe(child);
      }
      for (const child of Array.from(watched)) {
        if (child.parentElement === scroller) continue;
        watched.delete(child);
        resizeObserver.unobserve(child);
      }
    };

    watchChildren();
    const mutationObserver = new MutationObserver(() => {
      watchChildren();
      pin();
    });
    mutationObserver.observe(scroller, { childList: true });

    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, [scrollRef, shouldFollow, onPinned]);
}
