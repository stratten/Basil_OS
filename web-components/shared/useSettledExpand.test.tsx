// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettledExpand } from './useSettledExpand';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Harness({ isCollapsed }: { isCollapsed: boolean }) {
  const contentCollapsed = useSettledExpand(isCollapsed);
  return <div data-testid="content" data-collapsed={String(contentCollapsed)} />;
}

function contentCollapsed(container: HTMLElement): string | null {
  return container.querySelector('[data-testid="content"]')!.getAttribute('data-collapsed');
}

function setViewport(width: number, height: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
}

function frames(count: number) {
  for (let i = 0; i < count; i += 1) {
    act(() => {
      vi.advanceTimersByTime(16);
    });
  }
}

describe('useSettledExpand', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance', 'setTimeout', 'clearTimeout'] });
    setViewport(600, 560);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  function render(isCollapsed: boolean) {
    act(() => root.render(<Harness isCollapsed={isCollapsed} />));
  }

  it('is not collapsed on mount when expanded, and never waits for a resize', () => {
    render(false);
    expect(contentCollapsed(container)).toBe('false');
    frames(5);
    expect(contentCollapsed(container)).toBe('false');
  });

  it('collapses immediately', () => {
    render(false);
    render(true);
    expect(contentCollapsed(container)).toBe('true');
  });

  it('keeps content collapsed while the viewport is still changing and reveals it once the size settles', () => {
    render(true);
    setViewport(300, 64);
    render(false);
    expect(contentCollapsed(container)).toBe('true');

    frames(1);
    setViewport(400, 200);
    frames(1);
    setViewport(500, 400);
    frames(1);
    setViewport(600, 560);
    frames(1);
    expect(contentCollapsed(container)).toBe('true');

    frames(4);
    expect(contentCollapsed(container)).toBe('false');
  });

  it('does not reveal before any resize has been observed', () => {
    render(true);
    render(false);
    frames(10);
    expect(contentCollapsed(container)).toBe('true');
  });

  it('reveals after the failsafe when no resize ever arrives', () => {
    render(true);
    render(false);
    frames(70);
    expect(contentCollapsed(container)).toBe('false');
  });

  it('cancels a pending reveal when collapsed again before the window settles', () => {
    render(true);
    render(false);
    frames(2);
    render(true);
    expect(contentCollapsed(container)).toBe('true');
    setViewport(300, 64);
    frames(10);
    expect(contentCollapsed(container)).toBe('true');
  });
});
