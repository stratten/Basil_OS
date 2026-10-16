import { useLayoutEffect, useRef, useState, type RefObject, type TransitionEvent } from 'react';
import { settleWhenUntransitioned } from './presenceTransitionSettle';

export interface ExpandableHeightOptions {
  expanded: boolean;
  /** Height of the content when collapsed, measured from the live content element. Capped at the full content height. */
  measureCollapsedHeight: (content: HTMLElement) => number;
  /** Also keep `collapsedHeight` and `overflows` current (re-measured whenever the content resizes or `contentKey` changes). Components that clamp with CSS alone do not need this. */
  trackCollapsedHeight?: boolean;
  /** Decides whether collapsing hides anything, for content whose pixel heights are unreliable for that comparison (item margins and line boxes count toward the full height but not toward a measured item edge). Defaults to comparing the full height with the collapsed height. */
  detectOverflow?: (content: HTMLElement) => boolean;
  /** Changes whenever the content changes in a way that can move the collapsed height. */
  contentKey?: string | number;
}

export interface ExpandableHeight {
  frameRef: RefObject<HTMLDivElement>;
  contentRef: RefObject<HTMLDivElement>;
  /** True once the content is collapsed and any collapse animation has finished; false while expanding or expanded. */
  collapsed: boolean;
  /** Measured collapsed height in pixels, once known. Only maintained with `trackCollapsedHeight`. */
  collapsedHeight: number | undefined;
  /** Whether collapsing actually hides anything. Only maintained with `trackCollapsedHeight`. */
  overflows: boolean;
  handleTransitionEnd: (event: TransitionEvent<HTMLDivElement>) => void;
}

/**
 * The shared height animation behind every collapsible region (`ExpandableClamp`, `ExpandableList`).
 *
 * The frame's explicit pixel height is what animates, because collapsed content (a line clamp, a hidden tail) cannot be transitioned itself. The collapsed presentation is lifted at the start of an expand and restored only once a collapse has finished, so content is never cut off mid-animation. The duration and easing live in the consumer's CSS on the frame element.
 */
export function useExpandableHeight({
  expanded,
  measureCollapsedHeight,
  trackCollapsedHeight = false,
  detectOverflow,
  contentKey,
}: ExpandableHeightOptions): ExpandableHeight {
  const frameRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previousExpanded = useRef(expanded);
  const finishRef = useRef<(() => void) | null>(null);
  const measureRef = useRef(measureCollapsedHeight);
  measureRef.current = measureCollapsedHeight;
  const detectOverflowRef = useRef(detectOverflow);
  detectOverflowRef.current = detectOverflow;
  const [collapsed, setCollapsed] = useState(!expanded);
  const [collapsedHeight, setCollapsedHeight] = useState<number | undefined>(undefined);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    if (previousExpanded.current === expanded) return undefined;
    previousExpanded.current = expanded;
    const frame = frameRef.current;
    const content = contentRef.current;
    if (!frame || !content) {
      setCollapsed(!expanded);
      return undefined;
    }

    // Measured from the live frame so a toggle during a running animation continues from where it currently is.
    const startHeight = frame.offsetHeight;
    // A clipped element still reports its full content height as scrollHeight.
    const fullHeight = content.scrollHeight;
    const measured = measureRef.current(content);
    const clampedHeight = Number.isFinite(measured) ? Math.min(fullHeight, Math.ceil(measured)) : fullHeight;
    const targetHeight = expanded ? fullHeight : clampedHeight;

    const finish = () => {
      finishRef.current = null;
      frame.style.height = '';
      if (!expanded) setCollapsed(true);
    };
    finishRef.current = finish;

    if (expanded) setCollapsed(false);
    frame.style.height = `${startHeight}px`;
    // Reading layout commits the starting height so the next assignment transitions instead of jumping.
    void frame.offsetHeight;
    frame.style.height = `${targetHeight}px`;

    // transitionend never fires when there is no transition (reduced motion, or no height change), so settle those cases directly.
    const cancelSettle = settleWhenUntransitioned(frame, () => finishRef.current?.());
    return () => {
      cancelSettle();
      finishRef.current = null;
    };
  }, [expanded]);

  useLayoutEffect(() => {
    if (!trackCollapsedHeight) return undefined;
    const content = contentRef.current;
    if (!content) return undefined;
    const update = () => {
      const full = content.scrollHeight;
      const measured = measureRef.current(content);
      const next = Number.isFinite(measured) ? Math.min(full, Math.ceil(measured)) : full;
      setCollapsedHeight(previous => (previous === next ? previous : next));
      setOverflows(detectOverflowRef.current ? detectOverflowRef.current(content) : full - next > 1);
    };
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(content);
    return () => observer.disconnect();
  }, [trackCollapsedHeight, contentKey]);

  const handleTransitionEnd = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== 'height') return;
    finishRef.current?.();
  };

  return { frameRef, contentRef, collapsed, collapsedHeight, overflows, handleTransitionEnd };
}
