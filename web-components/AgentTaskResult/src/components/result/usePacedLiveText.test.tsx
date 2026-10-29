// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextWordBoundary, usePacedLiveText, type PacedLiveText } from '@shared/usePacedLiveText';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let latest: PacedLiveText;
let frameQueue: Map<number, FrameRequestCallback>;
let nextFrameId: number;
let clockMs: number;

function Harness({ revealKey, content, live }: { revealKey: string; content: string; live: boolean }) {
  latest = usePacedLiveText(revealKey, content, live);
  return <div>{latest.text}</div>;
}

function render(content: string, live: boolean, revealKey = 'task-1') {
  act(() => {
    root.render(<Harness revealKey={revealKey} content={content} live={live} />);
  });
}

/** Advances the fake clock and runs every frame that was queued before this call. */
function advance(ms: number) {
  clockMs += ms;
  const due = [...frameQueue.entries()];
  frameQueue.clear();
  act(() => {
    for (const [, callback] of due) callback(clockMs);
  });
}

function drain(maxFrames = 400) {
  for (let i = 0; i < maxFrames && frameQueue.size > 0; i += 1) advance(16);
}

const LONG_TEXT = Array.from({ length: 120 }, (_, index) => `word${index}`).join(' ');

describe('nextWordBoundary', () => {
  it('stops at the next whitespace so words are never cut', () => {
    expect(nextWordBoundary('alpha beta', 2)).toBe(5);
    expect(nextWordBoundary('alpha beta', 5)).toBe(5);
    expect(nextWordBoundary('alpha beta', 7)).toBe(10);
    expect(nextWordBoundary('alpha', 99)).toBe(5);
  });
});

describe('usePacedLiveText', () => {
  beforeEach(() => {
    frameQueue = new Map();
    nextFrameId = 1;
    clockMs = 0;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = nextFrameId;
      nextFrameId += 1;
      frameQueue.set(id, callback);
      return id;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      frameQueue.delete(id);
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it('shows text that is already present when a task is first seen, without replaying it', () => {
    render(LONG_TEXT, false);

    expect(latest.text).toBe(LONG_TEXT);
    expect(latest.isRevealing).toBe(false);
    expect(frameQueue.size).toBe(0);
  });

  it('never paces a task that was not seen running, even if its text arrives later', () => {
    render('', false);
    render(LONG_TEXT, false);

    expect(latest.text).toBe(LONG_TEXT);
    expect(latest.isRevealing).toBe(false);
  });

  it('reveals a large block that arrives at once progressively, on word boundaries, and finishes whole', () => {
    render('', true);
    render(LONG_TEXT, true);

    expect(latest.text.length).toBeLessThan(LONG_TEXT.length);
    expect(latest.isRevealing).toBe(true);

    advance(100);
    const afterFirstSteps = latest.text;
    expect(afterFirstSteps.length).toBeGreaterThan(0);
    expect(afterFirstSteps.length).toBeLessThan(LONG_TEXT.length);
    expect(LONG_TEXT.startsWith(afterFirstSteps)).toBe(true);
    expect(LONG_TEXT.charAt(afterFirstSteps.length)).toMatch(/^\s$/);

    drain();
    expect(latest.text).toBe(LONG_TEXT);
    expect(latest.isRevealing).toBe(false);
  });

  it('keeps draining after the run stops being live so the end of the answer is not cut off', () => {
    render('', true);
    render(LONG_TEXT, true);
    advance(100);
    render(LONG_TEXT, false);

    expect(latest.isRevealing).toBe(true);
    drain();

    expect(latest.text).toBe(LONG_TEXT);
    expect(latest.isRevealing).toBe(false);
  });

  it('paces a block that lands at once after the run has already finished streaming', () => {
    render('Short start. ', true);
    render('Short start. ', false);
    render(`Short start. ${LONG_TEXT}`, false);

    expect(latest.text.length).toBeLessThan(`Short start. ${LONG_TEXT}`.length);
    drain();
    expect(latest.text).toBe(`Short start. ${LONG_TEXT}`);
  });

  it('shows what is already there when a window opens mid-run and paces only what follows', () => {
    render('Already on screen.', true);

    expect(latest.text).toBe('Already on screen.');

    render(`Already on screen. ${LONG_TEXT}`, true);
    expect(latest.text.startsWith('Already on screen.')).toBe(true);
    expect(latest.text.length).toBeLessThan(`Already on screen. ${LONG_TEXT}`.length);
    drain();
    expect(latest.text).toBe(`Already on screen. ${LONG_TEXT}`);
  });

  it('shows another task whole instead of carrying over the previous task reveal position', () => {
    render('', true, 'task-1');
    render(LONG_TEXT, true, 'task-1');
    advance(50);

    render('A different finished answer with its own length.', false, 'task-2');

    expect(latest.text).toBe('A different finished answer with its own length.');
    expect(latest.isRevealing).toBe(false);
  });

  it('clamps to shorter content when the provisional text is replaced by a shorter final answer', () => {
    render('', true);
    render(LONG_TEXT, true);
    drain();
    expect(latest.text).toBe(LONG_TEXT);

    render('Final answer.', false);

    expect(latest.text).toBe('Final answer.');
    expect(latest.isRevealing).toBe(false);
  });

  it('shows text as it arrives when the reader prefers reduced motion', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    act(() => root.unmount());
    root = createRoot(container);

    render('', true);
    render(LONG_TEXT, true);

    expect(latest.text).toBe(LONG_TEXT);
    expect(latest.isRevealing).toBe(false);
  });

  it('stops animating when the component unmounts mid-reveal', () => {
    render('', true);
    render(LONG_TEXT, true);
    expect(frameQueue.size).toBe(1);

    act(() => root.unmount());

    expect(frameQueue.size).toBe(0);
    root = createRoot(container);
  });
});
