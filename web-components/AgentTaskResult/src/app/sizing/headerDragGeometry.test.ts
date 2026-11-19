import { describe, expect, it } from 'vitest';
import { measureHeaderDragGeometry } from './headerDragGeometry';

function rectAt(right: number): DOMRect {
  return { right, left: 0, top: 0, bottom: 0, width: right, height: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
}

function buildHeader({ controlsRight, rightEdge, rightClasses, offsetHeight }: {
  controlsRight: number;
  rightEdge: number;
  rightClasses: string;
  offsetHeight: number;
}): HTMLElement {
  const header = document.createElement('div');
  Object.defineProperty(header, 'offsetHeight', { value: offsetHeight });
  const controls = document.createElement('div');
  controls.setAttribute('data-agent-task-header-controls', '');
  controls.getBoundingClientRect = () => rectAt(controlsRight);
  const right = document.createElement('div');
  right.setAttribute('data-agent-task-header-bubble', '');
  right.className = `header-right ${rightClasses}`.trim();
  right.getBoundingClientRect = () => rectAt(rightEdge);
  header.append(controls, right);
  return header;
}

describe('measureHeaderDragGeometry', () => {
  it('drags the whole collapsed widget and keeps only the window controls clickable while nothing is running', () => {
    const header = buildHeader({ controlsRight: 112, rightEdge: 292, rightClasses: '', offsetHeight: 70 });

    expect(measureHeaderDragGeometry(header, { width: 300, height: 78 }, true)).toEqual({
      height: 78,
      interactiveRanges: [{ start: 0, end: 114 }],
    });
  });

  it('leaves the bubble itself draggable and protects only the Pause and Stop buttons that slide out beside it', () => {
    const header = buildHeader({ controlsRight: 112, rightEdge: 292, rightClasses: 'has-stop-action has-pause-action', offsetHeight: 70 });

    expect(measureHeaderDragGeometry(header, { width: 300, height: 78 }, true).interactiveRanges).toEqual([
      { start: 0, end: 114 },
      { start: 190, end: 248 },
    ]);
  });

  it('protects a single Stop button with the narrower open width', () => {
    const header = buildHeader({ controlsRight: 112, rightEdge: 292, rightClasses: 'has-stop-action', offsetHeight: 70 });

    expect(measureHeaderDragGeometry(header, { width: 300, height: 78 }, true).interactiveRanges).toEqual([
      { start: 0, end: 114 },
      { start: 218, end: 248 },
    ]);
  });

  it('drags across the expanded header only, so the strip stays off the sidebar toggle below it', () => {
    const header = buildHeader({ controlsRight: 112, rightEdge: 492, rightClasses: '', offsetHeight: 52 });

    expect(measureHeaderDragGeometry(header, { width: 500, height: 640 }, false).height).toBe(52);
  });

  it('keeps every range inside the window', () => {
    const header = buildHeader({ controlsRight: 112, rightEdge: 120, rightClasses: 'has-stop-action has-pause-action', offsetHeight: 52 });

    for (const range of measureHeaderDragGeometry(header, { width: 130, height: 78 }, true).interactiveRanges) {
      expect(range.start).toBeGreaterThanOrEqual(0);
      expect(range.end).toBeLessThanOrEqual(130);
      expect(range.end).toBeGreaterThan(range.start);
    }
  });
});
