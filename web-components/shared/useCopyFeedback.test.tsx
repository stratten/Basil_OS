// @vitest-environment jsdom

import { act } from 'react';
import type { ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { COPY_FEEDBACK_MS, useCopiedFlag, useCopyFeedback } from './useCopyFeedback';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Kind = 'richText' | 'markdown';

function KeyedHarness({ durationMs }: { durationMs?: number }) {
  const { copiedKey, flash } = useCopyFeedback<Kind>(durationMs);
  return (
    <div>
      <output data-testid="key">{copiedKey ?? 'none'}</output>
      <button type="button" data-testid="rich" onClick={() => flash('richText')} />
      <button type="button" data-testid="markdown" onClick={() => flash('markdown')} />
    </div>
  );
}

function FlagHarness() {
  const [copied, flashCopied] = useCopiedFlag();
  return (
    <div>
      <output data-testid="flag">{String(copied)}</output>
      <button type="button" data-testid="flash" onClick={flashCopied} />
    </div>
  );
}

describe('useCopyFeedback', () => {
  let container: HTMLDivElement;
  let roots: Root[];

  function mount(element: ReactElement): Root {
    const root = createRoot(container);
    roots.push(root);
    act(() => {
      root.render(element);
    });
    return root;
  }

  function text(testId: string): string | null {
    return container.querySelector(`[data-testid="${testId}"]`)!.textContent;
  }

  function click(testId: string) {
    act(() => {
      container.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`)!.click();
    });
  }

  function advance(ms: number) {
    act(() => {
      vi.advanceTimersByTime(ms);
    });
  }

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    container = document.createElement('div');
    document.body.appendChild(container);
    roots = [];
  });

  afterEach(() => {
    for (const root of roots) {
      act(() => {
        root.unmount();
      });
    }
    container.remove();
    vi.useRealTimers();
  });

  it('exposes the shared confirmation duration as 1500 ms', () => {
    expect(COPY_FEEDBACK_MS).toBe(1500);
  });

  it('shows the confirmation and reverts at exactly the default duration', () => {
    mount(<KeyedHarness />);
    expect(text('key')).toBe('none');

    click('rich');
    expect(text('key')).toBe('richText');

    advance(COPY_FEEDBACK_MS - 1);
    expect(text('key')).toBe('richText');

    advance(1);
    expect(text('key')).toBe('none');
  });

  it('honors a custom duration', () => {
    mount(<KeyedHarness durationMs={400} />);
    click('markdown');
    advance(399);
    expect(text('key')).toBe('markdown');
    advance(1);
    expect(text('key')).toBe('none');
  });

  it('restarts the window when the same key is flashed again before it reverts', () => {
    mount(<KeyedHarness />);
    click('rich');
    advance(1000);
    click('rich');
    advance(1000);
    expect(text('key')).toBe('richText');
    advance(500);
    expect(text('key')).toBe('none');
  });

  it('replaces the active key and never lets the earlier flash clear the later one', () => {
    mount(<KeyedHarness />);
    click('rich');
    advance(1000);
    click('markdown');
    expect(text('key')).toBe('markdown');

    advance(500);
    expect(text('key')).toBe('markdown');

    advance(1000);
    expect(text('key')).toBe('none');
  });

  it('clears its pending timer on unmount', () => {
    const root = mount(<KeyedHarness />);
    click('rich');
    expect(vi.getTimerCount()).toBe(1);

    act(() => {
      root.unmount();
    });
    roots = roots.filter((candidate) => candidate !== root);

    expect(vi.getTimerCount()).toBe(0);
  });

  it('exposes a boolean form whose flash takes no arguments', () => {
    mount(<FlagHarness />);
    expect(text('flag')).toBe('false');

    click('flash');
    expect(text('flag')).toBe('true');

    advance(COPY_FEEDBACK_MS);
    expect(text('flag')).toBe('false');
  });
});
