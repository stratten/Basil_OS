// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useExpandableHeight } from './useExpandableHeight';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let transitionDuration = '0.5s';
let frameHeight = 40;
let contentScrollHeight = 300;
let measuredCollapsedHeight = 80;
let latest: ReturnType<typeof useExpandableHeight>;
const resizeCallbacks: Array<() => void> = [];

function Harness({ expanded, track = false, contentKey }: { expanded: boolean; track?: boolean; contentKey?: number }) {
  latest = useExpandableHeight({
    expanded,
    measureCollapsedHeight: () => measuredCollapsedHeight,
    trackCollapsedHeight: track,
    contentKey,
  });
  return (
    <div ref={latest.frameRef} className="frame" onTransitionEnd={latest.handleTransitionEnd}>
      <div ref={latest.contentRef}>content</div>
    </div>
  );
}

function render(props: Parameters<typeof Harness>[0]) {
  act(() => {
    root.render(<Harness {...props} />);
  });
}

const frame = () => container.querySelector<HTMLDivElement>('.frame')!;

function endHeightTransition() {
  const event = new Event('transitionend', { bubbles: true });
  Object.assign(event, { propertyName: 'height' });
  act(() => {
    frame().dispatchEvent(event);
  });
}

beforeEach(() => {
  transitionDuration = '0.5s';
  frameHeight = 40;
  contentScrollHeight = 300;
  measuredCollapsedHeight = 80;
  resizeCallbacks.length = 0;
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) {
      resizeCallbacks.push(callback);
    }
    observe() {}
    disconnect() {}
  });
  vi.spyOn(window, 'getComputedStyle').mockImplementation(
    () => ({ transitionDuration, transitionDelay: '0s' }) as unknown as CSSStyleDeclaration,
  );
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => frameHeight });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => contentScrollHeight });
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', { configurable: true, value: () => [{}] });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('useExpandableHeight', () => {
  it('starts collapsed when mounted collapsed and expanded when mounted expanded', () => {
    render({ expanded: false });
    expect(latest.collapsed).toBe(true);
    render({ expanded: true });
    expect(latest.collapsed).toBe(false);
  });

  it('pins the live height, animates to the full height, and releases the height when the transition ends', () => {
    render({ expanded: false });
    render({ expanded: true });
    expect(latest.collapsed).toBe(false);
    expect(frame().style.height).toBe('300px');
    endHeightTransition();
    expect(frame().style.height).toBe('');
  });

  it('keeps the collapsed state off until a collapse has finished, and animates to the measured collapsed height', () => {
    render({ expanded: true });
    frameHeight = 300;
    render({ expanded: false });
    expect(latest.collapsed).toBe(false);
    expect(frame().style.height).toBe('80px');
    endHeightTransition();
    expect(latest.collapsed).toBe(true);
    expect(frame().style.height).toBe('');
  });

  it('caps the collapsed height at the full content height', () => {
    contentScrollHeight = 50;
    measuredCollapsedHeight = 120;
    render({ expanded: true });
    frameHeight = 50;
    render({ expanded: false });
    expect(frame().style.height).toBe('50px');
  });

  it('settles at once when there is no transition to wait for', () => {
    transitionDuration = '0s';
    render({ expanded: true });
    frameHeight = 300;
    render({ expanded: false });
    expect(latest.collapsed).toBe(true);
    expect(frame().style.height).toBe('');
  });

  it('ignores transitionend events for other properties', () => {
    render({ expanded: true });
    frameHeight = 300;
    render({ expanded: false });
    const event = new Event('transitionend', { bubbles: true });
    Object.assign(event, { propertyName: 'opacity' });
    act(() => {
      frame().dispatchEvent(event);
    });
    expect(latest.collapsed).toBe(false);
  });

  it('does not measure the collapsed height unless tracking is requested', () => {
    render({ expanded: false });
    expect(latest.collapsedHeight).toBeUndefined();
    expect(latest.overflows).toBe(false);
  });

  it('tracks the collapsed height and whether collapsing hides anything, and re-measures on resize', () => {
    render({ expanded: false, track: true, contentKey: 1 });
    expect(latest.collapsedHeight).toBe(80);
    expect(latest.overflows).toBe(true);

    contentScrollHeight = 60;
    act(() => {
      resizeCallbacks.forEach(callback => callback());
    });
    expect(latest.collapsedHeight).toBe(60);
    expect(latest.overflows).toBe(false);
  });
});
