// @vitest-environment jsdom

import { act, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SearchFocus } from './searchFocusStore';
import { collectMatchRanges, SEARCH_HIGHLIGHT_NAME, SEARCH_SECTION_ATTRIBUTE, useSearchHighlight } from './useSearchHighlight';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TURN_OWNERS = { ownerAttribute: 'data-run-content', fallbackOwnerId: 'turn-3' };

function buildContent(): HTMLElement {
  const container = document.createElement('div');
  container.innerHTML = `
    <section data-run-content="turn-1"><p>Plan the Lisbon offsite and LISBON hotels</p></section>
    <section data-run-content="turn-2"><p>Projector pricing only</p></section>
    <p>Latest turn mentions lisbon again</p>
    <script>lisbon()</script>
  `;
  return container;
}

function rangeTexts(ranges: Range[]): string[] {
  return ranges.map(range => range.toString());
}

describe('collectMatchRanges', () => {
  it('marks every case-insensitive occurrence inside the matched turns only', () => {
    const ranges = collectMatchRanges(buildContent(), ['lisbon'], ['turn-1'], TURN_OWNERS);
    expect(rangeTexts(ranges)).toEqual(['Lisbon', 'LISBON']);
  });

  it('treats text outside any earlier-turn card as the live turn', () => {
    const ranges = collectMatchRanges(buildContent(), ['lisbon'], ['turn-3'], TURN_OWNERS);
    expect(rangeTexts(ranges)).toEqual(['lisbon']);
  });

  it('finds several words and skips script text', () => {
    const ranges = collectMatchRanges(buildContent(), ['projector', 'pricing'], ['turn-2'], TURN_OWNERS);
    expect(rangeTexts(ranges)).toEqual(['Projector', 'pricing']);
    expect(collectMatchRanges(buildContent(), ['lisbon'], ['turn-1', 'turn-2', 'turn-3'], TURN_OWNERS)).toHaveLength(3);
  });

  it('returns nothing for no tokens, one-letter tokens, no turns, or a turn that is not open', () => {
    expect(collectMatchRanges(buildContent(), [], ['turn-1'], TURN_OWNERS)).toEqual([]);
    expect(collectMatchRanges(buildContent(), ['l'], ['turn-1'], TURN_OWNERS)).toEqual([]);
    expect(collectMatchRanges(buildContent(), ['lisbon'], [], TURN_OWNERS)).toEqual([]);
    expect(collectMatchRanges(buildContent(), ['lisbon'], ['turn-9'], TURN_OWNERS)).toEqual([]);
  });

  it('treats regex characters in a token literally and caps the number of ranges', () => {
    const container = document.createElement('div');
    container.innerHTML = `<p data-x>${'a.b '.repeat(500)}</p>`;
    expect(collectMatchRanges(container, ['a.b'], ['live'], { ownerAttribute: 'data-run-content', fallbackOwnerId: 'live' })).toHaveLength(300);
    expect(collectMatchRanges(container, ['a+b'], ['live'], { ownerAttribute: 'data-run-content', fallbackOwnerId: 'live' })).toEqual([]);
  });
});

describe('useSearchHighlight', () => {
  const registered = new Map<string, unknown>();
  const focus = (overrides: Partial<SearchFocus> = {}): SearchFocus => ({
    scopeId: 'root',
    query: 'lisbon',
    tokens: ['lisbon'],
    matchedIds: ['turn-1'],
    nonce: 1,
    ...overrides,
  });

  function Harness({ searchFocus, expandedKey = '' }: { searchFocus: SearchFocus | null; expandedKey?: string }) {
    const ref = useRef<HTMLDivElement>(null);
    useSearchHighlight(ref, searchFocus, TURN_OWNERS, expandedKey);
    return (
      <div ref={ref}>
        <section data-run-content="turn-1"><p>Lisbon hotels</p></section>
      </div>
    );
  }

  beforeEach(() => {
    registered.clear();
    class FakeHighlight {
      ranges: Range[];
      constructor(...ranges: Range[]) { this.ranges = ranges; }
    }
    Object.assign(globalThis, { Highlight: FakeHighlight });
    Object.defineProperty(CSS, 'highlights', {
      configurable: true,
      value: {
        set: (name: string, value: unknown) => { registered.set(name, value); },
        delete: (name: string) => { registered.delete(name); },
      },
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'Highlight');
    Reflect.deleteProperty(CSS, 'highlights');
  });

  it('registers the matching ranges, clears them when the focus is removed, and clears on unmount', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => { root.render(<Harness searchFocus={focus()} />); });
    expect((registered.get(SEARCH_HIGHLIGHT_NAME) as { ranges: Range[] }).ranges.map(range => range.toString())).toEqual(['Lisbon']);

    act(() => { root.render(<Harness searchFocus={null} />); });
    expect(registered.has(SEARCH_HIGHLIGHT_NAME)).toBe(false);

    act(() => { root.render(<Harness searchFocus={focus({ nonce: 2 })} />); });
    expect(registered.has(SEARCH_HIGHLIGHT_NAME)).toBe(true);
    act(() => { root.unmount(); });
    expect(registered.has(SEARCH_HIGHLIGHT_NAME)).toBe(false);
  });

  it('registers nothing when no rendered text matches', () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => { root.render(<Harness searchFocus={focus({ tokens: ['zebra'] })} />); });
    expect(registered.has(SEARCH_HIGHLIGHT_NAME)).toBe(false);
    act(() => { root.unmount(); });
  });

  it('does nothing in a browser without the Custom Highlight API', () => {
    Reflect.deleteProperty(CSS, 'highlights');
    const warn = vi.spyOn(console, 'error').mockImplementation(() => {});
    const container = document.createElement('div');
    const root = createRoot(container);
    expect(() => act(() => { root.render(<Harness searchFocus={focus()} />); })).not.toThrow();
    expect(registered.size).toBe(0);
    act(() => { root.unmount(); });
    warn.mockRestore();
  });

  describe('section marks', () => {
    function SectionHarness({ searchFocus }: { searchFocus: SearchFocus | null }) {
      const ref = useRef<HTMLDivElement>(null);
      useSearchHighlight(ref, searchFocus, TURN_OWNERS, '');
      return (
        <div ref={ref}>
          <section data-run-content="turn-1"><p>Lisbon hotels</p></section>
          <section data-run-content="turn-2"><p>Lisbon flights</p></section>
          <section data-run-content="turn-4"><p>Nothing relevant</p></section>
          <p>Latest turn mentions lisbon</p>
        </div>
      );
    }

    const sectionOf = (container: HTMLElement, id: string) => container.querySelector(`[data-run-content="${id}"]`);

    it('marks matched cards, calls the first one the jump target, and leaves unmatched and live content alone', () => {
      const container = document.createElement('div');
      const root = createRoot(container);
      act(() => { root.render(<SectionHarness searchFocus={focus({ matchedIds: ['turn-2', 'turn-1', 'turn-3', 'missing'] })} />); });
      expect(sectionOf(container, 'turn-2')?.getAttribute(SEARCH_SECTION_ATTRIBUTE)).toBe('jump');
      expect(sectionOf(container, 'turn-1')?.getAttribute(SEARCH_SECTION_ATTRIBUTE)).toBe('');
      expect(sectionOf(container, 'turn-4')?.hasAttribute(SEARCH_SECTION_ATTRIBUTE)).toBe(false);
      expect(container.querySelectorAll(`[${SEARCH_SECTION_ATTRIBUTE}]`)).toHaveLength(2);
      act(() => { root.unmount(); });
    });

    it('marks sections even in a browser without the Custom Highlight API', () => {
      Reflect.deleteProperty(CSS, 'highlights');
      const container = document.createElement('div');
      const root = createRoot(container);
      act(() => { root.render(<SectionHarness searchFocus={focus()} />); });
      expect(sectionOf(container, 'turn-1')?.getAttribute(SEARCH_SECTION_ATTRIBUTE)).toBe('jump');
      act(() => { root.unmount(); });
    });

    it('removes the marks when the focus is cleared or the component unmounts', () => {
      const container = document.createElement('div');
      const root = createRoot(container);
      act(() => { root.render(<SectionHarness searchFocus={focus()} />); });
      expect(container.querySelectorAll(`[${SEARCH_SECTION_ATTRIBUTE}]`)).toHaveLength(1);
      act(() => { root.render(<SectionHarness searchFocus={null} />); });
      expect(container.querySelectorAll(`[${SEARCH_SECTION_ATTRIBUTE}]`)).toHaveLength(0);
      act(() => { root.render(<SectionHarness searchFocus={focus({ nonce: 2 })} />); });
      expect(container.querySelectorAll(`[${SEARCH_SECTION_ATTRIBUTE}]`)).toHaveLength(1);
      act(() => { root.unmount(); });
      expect(container.querySelectorAll(`[${SEARCH_SECTION_ATTRIBUTE}]`)).toHaveLength(0);
    });

    it('does not restart the flash when content changes re-apply the marks', async () => {
      vi.useFakeTimers();
      try {
        const container = document.createElement('div');
        const root = createRoot(container);
        act(() => { root.render(<SectionHarness searchFocus={focus()} />); });
        const card = sectionOf(container, 'turn-1') as HTMLElement;
        const setAttribute = vi.spyOn(card, 'setAttribute');
        card.appendChild(document.createElement('span'));
        await act(async () => {
          await Promise.resolve();
          vi.advanceTimersByTime(300);
        });
        expect(setAttribute).not.toHaveBeenCalled();
        expect(card.getAttribute(SEARCH_SECTION_ATTRIBUTE)).toBe('jump');
        act(() => { root.unmount(); });
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
