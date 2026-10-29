import { act, createRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const stick = vi.hoisted(() => ({ isPinned: true }));
vi.mock('../../../shared/useStickToBottom', () => ({
  useStickToBottom: () => ({ isPinned: stick.isPinned, scrollToBottom: vi.fn() }),
}));

import CompanionStream, { HIGHLIGHT_MS, LEAVE_MS, type CompanionStreamHandle } from './CompanionStream';
import type { CompanionStreamEntry } from './companionStreamSelectors';
import type { CompanionItem } from './types';

type ObserverRecord = { target: Element; isIntersecting: boolean; intersectionRatio: number; intersectionRect: { height: number } };
let observerCallback: ((records: ObserverRecord[]) => void) | null = null;
let observed: Element[] = [];

class FakeIntersectionObserver {
  constructor(callback: (records: ObserverRecord[]) => void) {
    observerCallback = callback;
  }
  observe(target: Element) {
    observed.push(target);
  }
  disconnect() {
    observed = [];
  }
  unobserve() {}
  takeRecords() {
    return [];
  }
}

function itemEntry(id: string, seq: number): CompanionStreamEntry {
  const item = { id, seq, kind: 'insight', text: id } as unknown as CompanionItem;
  return { type: 'item', key: `item:${id}`, seq, item };
}

function renderStream(entries: CompanionStreamEntry[], overrides: Partial<React.ComponentProps<typeof CompanionStream>> = {}, ref?: React.Ref<CompanionStreamHandle>) {
  const props = {
    entries,
    renderEntry: (entry: CompanionStreamEntry) => <span>{entry.key}</span>,
    ready: true,
    baselineSeq: 0,
    unseen: [] as CompanionStreamEntry[],
    onSeen: vi.fn(),
    active: true,
    empty: <p>Nothing yet</p>,
    working: null,
    ...overrides,
  };
  const view = render(<CompanionStream ref={ref} {...props} />);
  return { props, view, rerender: (next: Partial<typeof props>) => view.rerender(<CompanionStream ref={ref} {...props} {...next} />) };
}

beforeEach(() => {
  stick.isPinned = true;
  observerCallback = null;
  observed = [];
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('CompanionStream', () => {
  it('is an aria-live log that shows the empty note only when there are no rows', () => {
    const empty = renderStream([]);
    expect(screen.getByRole('log', { name: 'Companion feed' })).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByText('Nothing yet')).toBeInTheDocument();
    empty.view.unmount();
    renderStream([itemEntry('a', 1)]);
    expect(screen.queryByText('Nothing yet')).toBeNull();
  });

  it('shows the new-items pill only while scrolled away, and jumps to the first unseen row', () => {
    const entries = [itemEntry('a', 1), itemEntry('b', 2), itemEntry('c', 3)];
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    stick.isPinned = true;
    const pinned = renderStream(entries, { unseen: entries.slice(1) });
    expect(screen.queryByRole('button', { name: /new item/ })).toBeNull();
    pinned.view.unmount();

    stick.isPinned = false;
    renderStream(entries, { unseen: entries.slice(1) });
    const pill = screen.getByRole('button', { name: 'Jump to 2 new items' });
    fireEvent.click(pill);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.instances[0]).toBe(document.querySelector('[data-stream-key="item:b"]'));
  });

  it('never animates the backlog and opens rows that arrive afterward', () => {
    const view = renderStream([itemEntry('a', 1), itemEntry('b', 2)], { baselineSeq: 2 });
    expect(document.querySelectorAll('.is-arriving')).toHaveLength(0);
    view.rerender({ entries: [itemEntry('a', 1), itemEntry('b', 2), itemEntry('c', 3)] });
    const rows = document.querySelectorAll('.companion-stream-row');
    expect(rows[0]).not.toHaveClass('is-arriving');
    expect(rows[2]).toHaveClass('is-arriving');
  });

  it('drops the arrival clipping once the row has finished opening, and ignores the card fade ending', () => {
    const view = renderStream([itemEntry('a', 1)], { baselineSeq: 1 });
    view.rerender({ entries: [itemEntry('a', 1), itemEntry('b', 2)] });
    const row = document.querySelectorAll('.companion-stream-row')[1] as HTMLElement;
    expect(row).toHaveClass('is-arriving');
    // jsdom has no AnimationEvent, so React never listens for animationend there; the row's own handler is called with the event fields it reads.
    const finish = (target: HTMLElement, animationName: string) => {
      const propsKey = Object.keys(row).find((key) => key.startsWith('__reactProps')) as string;
      const handler = (row as unknown as Record<string, { onAnimationEnd?: (event: unknown) => void }>)[propsKey].onAnimationEnd;
      act(() => handler?.({ target, currentTarget: row, animationName }));
    };
    finish(row.firstElementChild as HTMLElement, 'companion-row-arrive');
    finish(row, 'companion-row-fade');
    expect(row).toHaveClass('is-arriving');
    finish(row, 'companion-row-arrive');
    expect(row).not.toHaveClass('is-arriving');
  });

  it('does not animate rows that were already present when the pane remounted, even above the hydration baseline', () => {
    renderStream([itemEntry('a', 1), itemEntry('b', 5)], { baselineSeq: 0 });
    expect(document.querySelectorAll('.is-arriving')).toHaveLength(0);
  });

  it('reports the highest row actually on screen, ignoring slivers and hidden pages', () => {
    const entries = [itemEntry('a', 1), itemEntry('b', 2), itemEntry('c', 3)];
    const onSeen = vi.fn();
    renderStream(entries, { onSeen });
    expect(observed).toHaveLength(3);
    const [a, b, c] = observed;
    act(() => observerCallback?.([
      { target: a, isIntersecting: true, intersectionRatio: 1, intersectionRect: { height: 200 } },
      { target: b, isIntersecting: true, intersectionRatio: 0.9, intersectionRect: { height: 150 } },
      { target: c, isIntersecting: true, intersectionRatio: 0.05, intersectionRect: { height: 8 } },
    ]));
    expect(onSeen).toHaveBeenCalledWith(2);
  });

  it('counts a tall card as seen once enough of it is visible even though its ratio is small', () => {
    const onSeen = vi.fn();
    renderStream([itemEntry('tall', 4)], { onSeen });
    act(() => observerCallback?.([{ target: observed[0], isIntersecting: true, intersectionRatio: 0.2, intersectionRect: { height: 300 } }]));
    expect(onSeen).toHaveBeenCalledWith(4);
  });

  it('marks nothing seen while the pane is inactive', () => {
    renderStream([itemEntry('a', 1)], { active: false });
    expect(observed).toHaveLength(0);
  });

  it('scrolls to a row by key, highlights it briefly, and reports a missing row', () => {
    vi.useFakeTimers();
    Element.prototype.scrollIntoView = vi.fn();
    const ref = createRef<CompanionStreamHandle>();
    renderStream([itemEntry('a', 1), itemEntry('b', 2)], {}, ref);
    let found = false;
    act(() => {
      found = ref.current!.scrollToKey('item:b');
    });
    expect(found).toBe(true);
    expect(document.querySelector('[data-stream-key="item:b"]')).toHaveClass('is-highlighted');
    act(() => {
      vi.advanceTimersByTime(HIGHLIGHT_MS + 10);
    });
    expect(document.querySelector('[data-stream-key="item:b"]')).not.toHaveClass('is-highlighted');
    expect(ref.current!.scrollToKey('item:missing')).toBe(false);
  });

  it('shows the working row and footer after the last row', () => {
    renderStream([itemEntry('a', 1)], { working: <p>working</p>, footer: <p>footer</p> });
    const log = screen.getByRole('log');
    const text = log.textContent ?? '';
    expect(text.indexOf('item:a')).toBeLessThan(text.indexOf('working'));
    expect(text.indexOf('working')).toBeLessThan(text.indexOf('footer'));
  });

  it('plays an exit for a row that leaves the stream, then removes it', () => {
    vi.useFakeTimers();
    const view = renderStream([itemEntry('a', 1), itemEntry('b', 2)]);
    view.rerender({ entries: [itemEntry('a', 1)] });
    const leaving = document.querySelector('[data-stream-key="item:b"]');
    expect(leaving).toHaveClass('is-leaving');
    expect(leaving).toHaveAttribute('aria-hidden', 'true');
    act(() => {
      vi.advanceTimersByTime(LEAVE_MS + 10);
    });
    expect(document.querySelector('[data-stream-key="item:b"]')).toBeNull();
    expect(document.querySelector('[data-stream-key="item:a"]')).not.toHaveClass('is-leaving');
  });

  it('brings a restored row straight back without leaving it half-exited', () => {
    vi.useFakeTimers();
    const view = renderStream([itemEntry('a', 1), itemEntry('b', 2)]);
    view.rerender({ entries: [itemEntry('a', 1)] });
    view.rerender({ entries: [itemEntry('a', 1), itemEntry('b', 2)] });
    expect(document.querySelector('[data-stream-key="item:b"]')).not.toHaveClass('is-leaving');
    act(() => {
      vi.advanceTimersByTime(LEAVE_MS + 10);
    });
    expect(document.querySelectorAll('[data-stream-key="item:b"]')).toHaveLength(1);
  });

  it('removes a row immediately under reduced motion', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const view = renderStream([itemEntry('a', 1), itemEntry('b', 2)]);
    view.rerender({ entries: [itemEntry('a', 1)] });
    expect(document.querySelector('[data-stream-key="item:b"]')).toBeNull();
  });
});
