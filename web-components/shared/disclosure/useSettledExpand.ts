import { useEffect, useRef, useState } from 'react';

const SETTLED_FRAME_COUNT = 3;
const MAX_WAIT_MS = 1000;

/**
 * Keeps window content hidden while the host window animates open.
 *
 * Collapsing hides content before the window shrinks, so the animation only has
 * to relayout a header. Expanding with the content already visible forces the
 * page to relayout and repaint on every animation frame. This hook returns
 * `true` immediately on collapse and, on expand, stays `true` until the
 * viewport has changed size and then stopped changing, so the window grows
 * around a header-only page and the content appears once it has settled.
 *
 * `MAX_WAIT_MS` is only a failsafe for hosts where no resize ever arrives (for
 * example a browser tab or a window that was already full size); it is not the
 * expected path.
 */
export function useSettledExpand(isCollapsed: boolean): boolean {
  const [contentCollapsed, setContentCollapsed] = useState(isCollapsed);
  const wasCollapsedRef = useRef(isCollapsed);

  useEffect(() => {
    const wasCollapsed = wasCollapsedRef.current;
    wasCollapsedRef.current = isCollapsed;

    if (isCollapsed) {
      setContentCollapsed(true);
      return undefined;
    }
    if (!wasCollapsed) return undefined;

    let lastWidth = window.innerWidth;
    let lastHeight = window.innerHeight;
    let hasResized = false;
    let stableFrames = 0;
    const startedAt = performance.now();
    let frame = 0;

    const step = () => {
      const width = window.innerWidth;
      const height = window.innerHeight;
      if (width !== lastWidth || height !== lastHeight) {
        hasResized = true;
        stableFrames = 0;
        lastWidth = width;
        lastHeight = height;
      } else if (hasResized) {
        stableFrames += 1;
      }

      const settled = hasResized && stableFrames >= SETTLED_FRAME_COUNT;
      if (settled || performance.now() - startedAt >= MAX_WAIT_MS) {
        setContentCollapsed(false);
        return;
      }
      frame = window.requestAnimationFrame(step);
    };

    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  }, [isCollapsed]);

  return isCollapsed || contentCollapsed;
}
