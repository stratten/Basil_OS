// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResponseTimeLimit } from '../../types';
import ResponseCountdown from './ResponseCountdown';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const NOW = Date.parse('2026-10-04T23:40:00+00:00');
let container: HTMLDivElement;
let root: Root;

function limit(secondsFromNow: number, overrides: Partial<ResponseTimeLimit> = {}): ResponseTimeLimit {
  return { deadlineMs: NOW + secondsFromNow * 1000, limitSeconds: 120, onTimeout: 'deny', ...overrides };
}

function mount(timeLimit: ResponseTimeLimit, variant?: 'card' | 'inline') {
  act(() => {
    root.render(<ResponseCountdown timeLimit={timeLimit} variant={variant} />);
  });
}

const countdown = () => container.querySelector('.response-countdown') as HTMLElement;
const clock = () => container.querySelector('.response-countdown-clock')?.textContent;
const fill = () => container.querySelector('.response-countdown-fill') as HTMLElement;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe('ResponseCountdown', () => {
  it('shows the time left and what Basil will do at the deadline', () => {
    mount(limit(102));

    expect(clock()).toBe('1:42');
    expect(countdown().getAttribute('role')).toBe('timer');
    expect(countdown().getAttribute('aria-label')).toBe('Time left to respond: 1:42');
    expect(countdown().textContent).toContain("If you don't respond, Basil will treat this as declined and carry on.");
    expect(countdown().dataset.responseCountdownState).toBe('running');
    expect(countdown().className).toContain('response-countdown--card');
  });

  it('counts down each second and drains the bar', () => {
    mount(limit(60));
    expect(fill().style.transform).toBe('scaleX(0.5)');

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(clock()).toBe('0:30');
    expect(fill().style.transform).toBe('scaleX(0.25)');
  });

  it('turns urgent for the last ten seconds', () => {
    mount(limit(12));
    expect(countdown().dataset.responseCountdownState).toBe('running');

    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    expect(clock()).toBe('0:10');
    expect(countdown().dataset.responseCountdownState).toBe('urgent');
  });

  it('says the time is up at zero, then stops ticking', () => {
    mount(limit(3, { onTimeout: 'stop_and_ask' }));

    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    expect(clock()).toBe('0:00');
    expect(countdown().dataset.responseCountdownState).toBe('expired');
    expect(countdown().textContent).toContain('Time limit reached. Basil is stopping the command.');
    expect(fill().style.transform).toBe('scaleX(0)');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('starts expired when the deadline already passed, for a request reopened late', () => {
    mount(limit(-45));

    expect(clock()).toBe('0:00');
    expect(countdown().dataset.responseCountdownState).toBe('expired');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('never draws the bar wider than the whole wait', () => {
    mount(limit(500));

    expect(fill().style.transform).toBe('scaleX(1)');
  });

  it('drops the box in the inline variant used inside a waiting turn', () => {
    mount(limit(30), 'inline');

    expect(countdown().className).toContain('response-countdown--inline');
    expect(countdown().className).not.toContain('response-countdown--card');
  });

  it('follows a new deadline and clears its timer when removed', () => {
    mount(limit(30));
    mount(limit(90));
    expect(clock()).toBe('1:30');

    act(() => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
    root = createRoot(container);
  });
});
