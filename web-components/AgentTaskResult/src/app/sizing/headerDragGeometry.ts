import { useEffect, useRef, type RefObject } from 'react';
import { reportWidgetHeaderDragGeometry } from '../../services/bridge';

/** A horizontal span of the header, in window coordinates, where a mouse-down must reach the page instead of starting a window drag. */
export interface HeaderInteractiveRange {
  start: number;
  end: number;
}

export interface HeaderDragGeometry {
  /** How far down from the top of the window a mouse-down drags it. */
  height: number;
  interactiveRanges: HeaderInteractiveRange[];
}

/** The bubble at the right end of the header. It is not a control, so it drags the window like the rest of the header. */
const HEADER_BUBBLE_WIDTH_PX = 44;
/** The header-right box is this wide while Stop alone, or Pause with Stop, is showing (see .header-right in shell-and-sidebar.css). */
const HEADER_RIGHT_WIDTH_WITH_STOP_PX = 74;
const HEADER_RIGHT_WIDTH_WITH_PAUSE_PX = 102;
/** A little slack past the window controls so a click on their edge still reaches them. */
const CONTROLS_EDGE_SLACK_PX = 2;

function interactiveRangeOf(start: number, end: number): HeaderInteractiveRange[] {
  return end > start ? [{ start, end }] : [];
}

/**
 * Works out which part of the header can drag the window.
 *
 * The collapsed widget is nothing but header, so all of it drags. The expanded header drags across its own height only, which keeps the drag strip off the sidebar toggle below it.
 * The only spans that must stay clickable are the window controls on the left and, while a run is active, the Pause and Stop buttons that slide out to the left of the bubble on hover. Those buttons are hidden until hovered, so their span is sized for the open state, not the one measured now.
 */
export function measureHeaderDragGeometry(
  header: HTMLElement,
  viewport: { width: number; height: number },
  isCollapsed: boolean,
): HeaderDragGeometry {
  const controls = header.querySelector<HTMLElement>('[data-agent-task-header-controls]');
  const right = header.querySelector<HTMLElement>('[data-agent-task-header-bubble]');
  const ranges: HeaderInteractiveRange[] = [];

  if (controls) {
    ranges.push(...interactiveRangeOf(0, controls.getBoundingClientRect().right + CONTROLS_EDGE_SLACK_PX));
  }

  if (right?.classList.contains('has-stop-action')) {
    const openWidth = right.classList.contains('has-pause-action')
      ? HEADER_RIGHT_WIDTH_WITH_PAUSE_PX
      : HEADER_RIGHT_WIDTH_WITH_STOP_PX;
    const rightEdge = right.getBoundingClientRect().right;
    ranges.push(...interactiveRangeOf(rightEdge - openWidth, rightEdge - HEADER_BUBBLE_WIDTH_PX));
  }

  return {
    height: isCollapsed ? viewport.height : header.offsetHeight,
    interactiveRanges: ranges.map(range => ({
      start: Math.max(0, Math.round(range.start)),
      end: Math.min(viewport.width, Math.round(range.end)),
    })),
  };
}

/**
 * Tells the native window which part of the header drags it, now and whenever the header changes: collapsing or expanding, a run starting or ending (Pause and Stop appear or go), or the window being resized.
 */
export function useHeaderDragGeometry(
  headerRef: RefObject<HTMLElement | null>,
  { enabled, isCollapsed, layoutKey }: { enabled: boolean; isCollapsed: boolean; layoutKey: string },
): void {
  const lastSentRef = useRef('');

  useEffect(() => {
    const header = headerRef.current;
    if (!enabled || !header) return;

    const report = () => {
      const geometry = measureHeaderDragGeometry(
        header,
        { width: window.innerWidth, height: window.innerHeight },
        isCollapsed,
      );
      const signature = JSON.stringify(geometry);
      if (signature === lastSentRef.current) return;
      lastSentRef.current = signature;
      reportWidgetHeaderDragGeometry(geometry.height, geometry.interactiveRanges);
    };

    report();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(report);
    observer.observe(header);
    return () => observer.disconnect();
  }, [headerRef, enabled, isCollapsed, layoutKey]);
}
