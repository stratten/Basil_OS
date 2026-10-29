// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatCountdown, useCountdown } from './useCountdown';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Probe({ targetMs }: { targetMs: number | null }) {
  const remaining = useCountdown(targetMs);
  return <div data-testid="probe">{String(remaining)}</div>;
}

describe('formatCountdown', () => {
  it('formats minutes and seconds, and hours when needed', () => {
    expect(formatCountdown(0)).toBe('0:00');
    expect(formatCountdown(9)).toBe('0:09');
    expect(formatCountdown(161)).toBe('2:41');
    expect(formatCountdown(3725)).toBe('1:02:05');
    expect(formatCountdown(-4)).toBe('0:00');
  });
});

describe('useCountdown', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-26T10:00:00Z'));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  const probeText = () => container.querySelector('[data-testid="probe"]')?.textContent;

  it('counts down once per second and stops at zero', () => {
    const target = Date.now() + 3000;
    act(() => root.render(<Probe targetMs={target} />));
    expect(probeText()).toBe('3');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(probeText()).toBe('2');

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(probeText()).toBe('0');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reports null without a target and starts a new countdown when the target changes', () => {
    act(() => root.render(<Probe targetMs={null} />));
    expect(probeText()).toBe('null');
    expect(vi.getTimerCount()).toBe(0);

    act(() => root.render(<Probe targetMs={Date.now() + 90_000} />));
    expect(probeText()).toBe('90');
  });

  it('clears its timer on unmount', () => {
    act(() => root.render(<Probe targetMs={Date.now() + 60_000} />));
    expect(vi.getTimerCount()).toBe(1);
    act(() => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
    root = createRoot(container);
  });
});
