import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { scrollVerticallyIntoView } from './scrollVerticallyIntoView';

function rect(top: number, bottom: number): DOMRect {
  return { top, bottom, height: bottom - top, left: 0, right: 10, width: 10, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
}

function buildScroller(scrollerTop: number, scrollerBottom: number, overflowing = true) {
  const outer = document.createElement('div');
  const scroller = document.createElement('div');
  scroller.style.overflowY = 'auto';
  Object.defineProperty(scroller, 'scrollHeight', { value: overflowing ? 500 : 100, configurable: true });
  Object.defineProperty(scroller, 'clientHeight', { value: 100, configurable: true });
  scroller.getBoundingClientRect = () => rect(scrollerTop, scrollerBottom);
  const target = document.createElement('div');
  scroller.appendChild(target);
  outer.appendChild(scroller);
  document.body.appendChild(outer);
  const scrollTo = vi.fn();
  scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo;
  scroller.scrollTop = 40;
  return { outer, scroller, target, scrollTo };
}

describe('scrollVerticallyIntoView', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('scrolls up by the amount the target hangs above the scroller', () => {
    const { target, scrollTo } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(80, 110);

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollTo).toHaveBeenCalledWith({ top: 20, behavior: 'auto' });
  });

  it('scrolls down by the amount the target hangs below the scroller', () => {
    const { target, scrollTo } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(170, 230);

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollTo).toHaveBeenCalledWith({ top: 70, behavior: 'auto' });
  });

  it('does nothing when the target is already fully visible', () => {
    const { target, scrollTo } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(120, 150);

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('aligns the top of a target taller than the scroller', () => {
    const { target, scrollTo } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(130, 400);

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollTo).toHaveBeenCalledWith({ top: 70, behavior: 'auto' });
  });

  it('aligns the bottom edge for block end and forwards the behavior', () => {
    const { target, scrollTo } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(150, 260);

    scrollVerticallyIntoView(target, { block: 'end', behavior: 'smooth' });

    expect(scrollTo).toHaveBeenCalledWith({ top: 100, behavior: 'smooth' });
  });

  it('ignores a scroller that has no overflow and never scrolls any ancestor', () => {
    const { target, outer, scroller, scrollTo } = buildScroller(100, 200, false);
    target.getBoundingClientRect = () => rect(300, 330);
    const outerScrollTo = vi.fn();
    outer.scrollTo = outerScrollTo as unknown as typeof outer.scrollTo;

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollTo).not.toHaveBeenCalled();
    expect(outerScrollTo).not.toHaveBeenCalled();
    expect(scroller.scrollLeft).toBe(0);
    expect(outer.scrollLeft).toBe(0);
  });

  it('never calls the browser scrollIntoView, which scrolls horizontally', () => {
    const { target } = buildScroller(100, 200);
    target.getBoundingClientRect = () => rect(300, 330);
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it('falls back to assigning scrollTop when scrollTo is unavailable', () => {
    const { target, scroller } = buildScroller(100, 200);
    (scroller as { scrollTo?: unknown }).scrollTo = undefined;
    target.getBoundingClientRect = () => rect(170, 230);

    scrollVerticallyIntoView(target, { block: 'nearest' });

    expect(scroller.scrollTop).toBe(70);
  });
});
