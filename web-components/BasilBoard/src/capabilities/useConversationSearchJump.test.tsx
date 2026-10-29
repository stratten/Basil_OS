// @vitest-environment jsdom

import { act, useRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSearchFocus, getSearchFocus } from '@shared/search/searchFocusStore';
import { useConversationSearchJump } from './useConversationSearchJump';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({ getConversationSearchMatches: vi.fn() }));
vi.mock('../services/api', () => apiMocks);

type JumpApi = ReturnType<typeof useConversationSearchJump>;

interface Harness {
  api: () => JumpApi;
  viewport: () => HTMLElement;
  pinned: { current: boolean };
  setProps: (props: { selectedConversationId: string | undefined; query: string }) => void;
  unmount: () => void;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function mountHarness(initial: { selectedConversationId: string | undefined; query: string }): Harness {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const pinned = { current: true };
  let latest: JumpApi | undefined;
  let viewportElement: HTMLElement | null = null;

  function Component(props: { selectedConversationId: string | undefined; query: string }) {
    const viewportRef = useRef<HTMLDivElement | null>(null);
    latest = useConversationSearchJump({
      viewportRef,
      pinnedToBottomRef: pinned,
      selectedConversationId: props.selectedConversationId,
      query: props.query,
    });
    return (
      <div
        ref={(element) => {
          viewportRef.current = element;
          viewportElement = element;
        }}
      >
        <article data-message-id="m1">First</article>
        <article data-message-id="m2">Second</article>
        <article data-message-id='odd"id'>Odd</article>
      </div>
    );
  }

  const render = (props: { selectedConversationId: string | undefined; query: string }) => {
    act(() => root.render(<Component {...props} />));
  };
  render(initial);

  return {
    api: () => latest as JumpApi,
    viewport: () => viewportElement as HTMLElement,
    pinned,
    setProps: render,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function stubLayout(viewport: HTMLElement, tops: Record<string, number>) {
  viewport.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
  for (const [id, top] of Object.entries(tops)) {
    const element = viewport.querySelector<HTMLElement>(`[data-message-id="${id.replace(/"/g, '\\"')}"]`);
    if (element) element.getBoundingClientRect = () => ({ top }) as DOMRect;
  }
}

describe('useConversationSearchJump', () => {
  let harness: Harness;
  let warn: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    clearSearchFocus();
    apiMocks.getConversationSearchMatches.mockReset();
    warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    harness?.unmount();
    warn.mockRestore();
    clearSearchFocus();
  });

  it('scrolls to the first matching message, releases the bottom pin and publishes the focus once history has loaded', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_message_ids: ['m2', 'm1'] });
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });
    stubLayout(harness.viewport(), { m1: 40, m2: 300 });
    harness.viewport().scrollTop = 100;

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    await flush();
    expect(getSearchFocus()).toBeNull();

    act(() => harness.api().historyLoaded(token));
    await flush();

    expect(apiMocks.getConversationSearchMatches).toHaveBeenCalledWith('c1', 'lisbon');
    expect(harness.pinned.current).toBe(false);
    expect(harness.viewport().scrollTop).toBe(100 + 300 - 8);
    expect(getSearchFocus()).toMatchObject({
      scopeId: 'c1',
      query: 'lisbon',
      tokens: ['lisbon'],
      matchedIds: ['m2', 'm1'],
    });
  });

  it('waits for the matches when history finishes first', async () => {
    const matches = deferred<{ tokens: string[]; matched_message_ids: string[] }>();
    apiMocks.getConversationSearchMatches.mockReturnValue(matches.promise);
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });
    stubLayout(harness.viewport(), { m1: 60 });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();
    expect(getSearchFocus()).toBeNull();

    matches.resolve({ tokens: ['lisbon'], matched_message_ids: ['m1'] });
    await flush();
    expect(getSearchFocus()?.matchedIds).toEqual(['m1']);
    expect(harness.pinned.current).toBe(false);
  });

  it('ignores a stale click whose matches arrive after a newer selection', async () => {
    const first = deferred<{ tokens: string[]; matched_message_ids: string[] }>();
    apiMocks.getConversationSearchMatches.mockReturnValueOnce(first.promise);
    harness = mountHarness({ selectedConversationId: 'c2', query: 'lisbon' });

    let staleToken = 0;
    act(() => {
      staleToken = harness.api().begin('c1', 'lisbon');
    });
    act(() => {
      harness.api().begin('c2', '');
    });
    first.resolve({ tokens: ['lisbon'], matched_message_ids: ['m1'] });
    await flush();
    act(() => harness.api().historyLoaded(staleToken));
    await flush();

    expect(getSearchFocus()).toBeNull();
    expect(harness.pinned.current).toBe(true);
  });

  it('leaves the conversation at the bottom when only the title matched', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_message_ids: [] });
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();

    expect(getSearchFocus()).toBeNull();
    expect(harness.pinned.current).toBe(true);
  });

  it('opens normally and warns when the match lookup fails', async () => {
    apiMocks.getConversationSearchMatches.mockRejectedValue(new Error('offline'));
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();

    expect(warn).toHaveBeenCalled();
    expect(getSearchFocus()).toBeNull();
    expect(harness.pinned.current).toBe(true);
  });

  it('does not look anything up for a blank search box', () => {
    harness = mountHarness({ selectedConversationId: 'c1', query: '   ' });
    act(() => {
      harness.api().begin('c1', '   ');
    });
    expect(apiMocks.getConversationSearchMatches).not.toHaveBeenCalled();
  });

  it('does not jump when the matched conversation is no longer the open one', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_message_ids: ['m1'] });
    harness = mountHarness({ selectedConversationId: 'other', query: 'lisbon' });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();

    expect(getSearchFocus()).toBeNull();
    expect(harness.pinned.current).toBe(true);
  });

  it('clears the focus when the search box is emptied', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_message_ids: ['m1'] });
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });
    stubLayout(harness.viewport(), { m1: 10 });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();
    expect(getSearchFocus()).not.toBeNull();

    harness.setProps({ selectedConversationId: 'c1', query: '' });
    expect(getSearchFocus()).toBeNull();
  });

  it('clears the focus on cancel and on unmount', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['lisbon'], matched_message_ids: ['m1'] });
    harness = mountHarness({ selectedConversationId: 'c1', query: 'lisbon' });
    stubLayout(harness.viewport(), { m1: 10 });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();
    act(() => harness.api().cancel());
    expect(getSearchFocus()).toBeNull();

    act(() => {
      token = harness.api().begin('c1', 'lisbon');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();
    expect(getSearchFocus()).not.toBeNull();
    harness.unmount();
    expect(getSearchFocus()).toBeNull();
    harness = mountHarness({ selectedConversationId: undefined, query: '' });
  });

  it('finds a message whose id contains a quote', async () => {
    apiMocks.getConversationSearchMatches.mockResolvedValue({ tokens: ['odd'], matched_message_ids: ['odd"id'] });
    harness = mountHarness({ selectedConversationId: 'c1', query: 'odd' });
    stubLayout(harness.viewport(), { 'odd"id': 500 });

    let token = 0;
    act(() => {
      token = harness.api().begin('c1', 'odd');
    });
    act(() => harness.api().historyLoaded(token));
    await flush();

    expect(harness.viewport().scrollTop).toBe(500 - 8);
  });
});
