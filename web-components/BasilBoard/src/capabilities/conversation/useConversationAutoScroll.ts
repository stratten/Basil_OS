import { useEffect, type MutableRefObject, type RefObject } from 'react';

/** Keeps the transcript pinned to the bottom while content grows, as long as the user has not scrolled away. */
export function useConversationAutoScroll(
  viewportRef: RefObject<HTMLDivElement>,
  pinnedRef: MutableRefObject<boolean>,
  enabled: boolean,
): void {
  useEffect(() => {
    const viewport = viewportRef.current;
    if (
      !enabled
      || !viewport
      || typeof globalThis.ResizeObserver === 'undefined'
      || typeof globalThis.MutationObserver === 'undefined'
      || typeof globalThis.requestAnimationFrame !== 'function'
    ) return undefined;
    let frameId = 0;
    const followBottom = () => {
      if (frameId) return;
      frameId = globalThis.requestAnimationFrame(() => {
        frameId = 0;
        if (pinnedRef.current) viewport.scrollTop = viewport.scrollHeight;
      });
    };
    const resizeObserver = new globalThis.ResizeObserver(followBottom);
    const observeChildren = () => {
      resizeObserver.disconnect();
      for (const child of Array.from(viewport.children)) resizeObserver.observe(child);
    };
    observeChildren();
    const mutationObserver = new globalThis.MutationObserver(observeChildren);
    mutationObserver.observe(viewport, { childList: true });
    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
      if (frameId) globalThis.cancelAnimationFrame(frameId);
    };
  }, [enabled, pinnedRef, viewportRef]);
}
