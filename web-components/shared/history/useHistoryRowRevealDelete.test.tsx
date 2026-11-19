// @vitest-environment jsdom

import { act, type WheelEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { useHistoryRowRevealDelete } from './useHistoryRowRevealDelete';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function mountHook(options: { enabled: boolean; actionWidth?: number }) {
  const result: { current: ReturnType<typeof useHistoryRowRevealDelete> | null } = { current: null };
  function Probe() {
    result.current = useHistoryRowRevealDelete(options);
    return null;
  }
  const container = document.createElement('div');
  const root = createRoot(container);
  act(() => root.render(<Probe />));
  return { result, unmount: () => act(() => root.unmount()) };
}

function swipe(deltaX: number): WheelEvent<HTMLElement> {
  return { deltaX, deltaY: 0, stopPropagation: () => {} } as unknown as WheelEvent<HTMLElement>;
}

describe('useHistoryRowRevealDelete action width', () => {
  it('opens at the default 60px for single-action rows', () => {
    const { result, unmount } = mountHook({ enabled: true });
    act(() => result.current?.handleWheel(swipe(40)));
    expect(result.current?.isOpen).toBe(false);
    act(() => result.current?.handleWheel(swipe(30)));
    expect(result.current?.isOpen).toBe(true);
    expect(result.current?.offset).toBe(60);
    unmount();
  });

  it('requires and settles at the wider width when two actions are revealed', () => {
    const { result, unmount } = mountHook({ enabled: true, actionWidth: 120 });
    act(() => result.current?.handleWheel(swipe(100)));
    expect(result.current?.isOpen).toBe(false);
    act(() => result.current?.handleWheel(swipe(30)));
    expect(result.current?.isOpen).toBe(true);
    expect(result.current?.offset).toBe(120);
    unmount();
  });

  it('ignores swipes when disabled', () => {
    const { result, unmount } = mountHook({ enabled: false, actionWidth: 120 });
    act(() => result.current?.handleWheel(swipe(200)));
    expect(result.current?.isOpen).toBe(false);
    expect(result.current?.offset).toBe(0);
    unmount();
  });
});
