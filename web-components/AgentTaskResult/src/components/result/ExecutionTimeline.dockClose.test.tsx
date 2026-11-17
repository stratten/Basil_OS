// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProgressStepsSection } from './ExecutionTimeline';
import type { TimelineEntry } from '../../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let animationFrames: FrameRequestCallback[];

const timeline: TimelineEntry[] = Array.from({ length: 5 }, (_, index) => ({
  id: `entry-${index}`,
  type: 'step',
  timestamp: `2026-11-15T12:00:0${index}Z`,
  content: `Step ${index + 1} reading a file`,
  metadata: { progress_step: `Step ${index + 1} reading a file` },
}));

const body = () => container.querySelector<HTMLElement>('.execution-activity-dock-body')!;
const header = () => container.querySelector<HTMLButtonElement>('.execution-activity-dock-header')!;
const rowCount = () => body().querySelectorAll('.execution-step-row').length;

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

function runPendingFrames() {
  act(() => {
    while (animationFrames.length > 0) animationFrames.shift()?.(0);
  });
}

function endFold() {
  act(() => {
    body().dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'grid-template-rows' }));
  });
}

beforeEach(() => {
  animationFrames = [];
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => animationFrames.push(callback)));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
  // jsdom loads no stylesheet, so declare the dock body's real transition. Without one the hook treats the exit as untransitioned and releases the rows at once.
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transitionDuration: '0.4s', transitionDelay: '0s' } as CSSStyleDeclaration);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(
      <ProgressStepsSection
        steps={[]}
        timeline={timeline}
        isProcessing
        presentation="dock"
        status={{ tone: 'live', label: 'Working', detail: '12s' }}
      />,
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('live activity dock closing', () => {
  it('keeps its rows mounted while the height folds away and releases them when the fold ends', () => {
    expect(rowCount()).toBe(0);

    click(header());
    runPendingFrames();
    expect(body().classList.contains('is-open')).toBe(true);
    expect(rowCount()).toBeGreaterThan(0);

    click(header());
    expect(body().classList.contains('is-open')).toBe(false);
    expect(rowCount()).toBeGreaterThan(0);
    expect(body().getAttribute('aria-hidden')).toBe('true');
    expect(body().hasAttribute('inert')).toBe(true);

    endFold();
    expect(rowCount()).toBe(0);
  });

  it('ignores the transitionend of properties other than the height fold', () => {
    click(header());
    runPendingFrames();
    click(header());

    act(() => {
      body().dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'opacity' }));
    });
    expect(rowCount()).toBeGreaterThan(0);

    endFold();
    expect(rowCount()).toBe(0);
  });

  it('keeps showing the full list, not the short trail, while closing from Full Details', () => {
    click(header());
    runPendingFrames();
    const trailRows = rowCount();

    click(container.querySelector('.execution-activity-dock-control')!);
    const fullRows = rowCount();
    expect(fullRows).toBeGreaterThan(trailRows);

    click(header());
    expect(rowCount()).toBe(fullRows);

    endFold();
    expect(rowCount()).toBe(0);
  });

  it('opens again from the short trail after a close that started in Full Details', () => {
    click(header());
    runPendingFrames();
    const trailRows = rowCount();
    click(container.querySelector('.execution-activity-dock-control')!);
    click(header());
    endFold();

    click(header());
    runPendingFrames();
    expect(body().classList.contains('is-open')).toBe(true);
    expect(rowCount()).toBe(trailRows);
  });
});
