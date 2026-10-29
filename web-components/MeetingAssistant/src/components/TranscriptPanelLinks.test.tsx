import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TranscriptLineDTO } from '../bridge/types';

vi.mock('../bridge/meetingBridge', () => ({ copyText: vi.fn(), focusTranscript: vi.fn(), focusCompanionItem: vi.fn() }));

import { LINK_FLASH_MS, CompanionLinksProvider, type CompanionLinks } from '../companion/companionLinks';
import type { CompanionItem } from '../companion/types';
import TranscriptPanel, { __getTranscriptRowRenderCountForTests, __resetTranscriptRowRenderCountsForTests } from './TranscriptPanel';

const line = (id: string, text: string, start: number | null, end: number | null): TranscriptLineDTO => ({
  id, text, speakerId: null, isInterim: false, displayStart: '0:00:01', timelineStartSeconds: start, timelineEndSeconds: end, source: null, lineComplete: true,
});

const item = (id: string, seq: number, start: number, end: number, overrides: Partial<CompanionItem> = {}): CompanionItem => ({
  id, seq, kind: 'suggestion', text: `Note ${id}`, confidence: 0.5, citations: [], no_source: false,
  transcript_range: { start, end, turn_ids: [] }, trigger: 'periodic', watch_id: null, truncated: false, pinned: false, dismissed: false,
  ...overrides,
});

const transcript = [line('l1', 'First line', 0, 4), line('l2', 'Second line', 5, 9), line('l3', 'Third line', 10, 14), line('l4', 'Untimed line', null, null)];
const ui = { transcriptionState: 'idle', isApplyingWindowedRetranscription: false };

function makeLinks(overrides: Partial<CompanionLinks> = {}): CompanionLinks {
  return {
    items: [],
    hoveredItemId: null,
    hover: vi.fn(),
    canShowInTranscript: () => true,
    showInTranscript: vi.fn(),
    showInCompanion: vi.fn(),
    transcriptFocus: null,
    companionFocus: null,
    ...overrides,
  };
}

function renderPanel(links: CompanionLinks, lines: TranscriptLineDTO[] = transcript) {
  const view = render(
    <CompanionLinksProvider value={links}>
      <TranscriptPanel transcript={lines} ui={ui} />
    </CompanionLinksProvider>,
  );
  return {
    ...view,
    rerenderWith: (next: CompanionLinks, nextLines: TranscriptLineDTO[] = lines) =>
      view.rerender(
        <CompanionLinksProvider value={next}>
          <TranscriptPanel transcript={nextLines} ui={ui} />
        </CompanionLinksProvider>,
      ),
  };
}

const rowOf = (text: string) => screen.getByText(text).closest('.meeting-transcript-row') as HTMLElement;

describe('TranscriptPanel Companion links', () => {
  beforeEach(() => {
    __resetTranscriptRowRenderCountsForTests();
    vi.useFakeTimers();
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows no chips and no gutter without links or without items', () => {
    const { container, unmount } = renderPanel(makeLinks());
    expect(container.querySelector('.meeting-transcript-link-chip')).toBeNull();
    expect(container.querySelector('.has-links')).toBeNull();
    unmount();
    render(<TranscriptPanel transcript={transcript} ui={ui} />);
    expect(document.querySelector('.meeting-transcript-link-chip')).toBeNull();
  });

  it('puts one chip on the last line of the span and opens the card on click', () => {
    const links = makeLinks({ items: [item('i1', 1, 5, 14)] });
    renderPanel(links);
    const chip = within(rowOf('Third line')).getByRole('button', { name: /Show the suggestion from the Companion: Note i1/ });
    expect(rowOf('Third line')).toHaveClass('has-links');
    expect(within(rowOf('Second line')).queryByRole('button')).toBeNull();
    fireEvent.click(chip);
    expect(links.showInCompanion).toHaveBeenCalledWith('i1');
  });

  it('collapses several items on one line to a count chip that opens a list', () => {
    const links = makeLinks({ items: [item('i1', 1, 5, 8), item('i2', 2, 6, 8, { kind: 'answer', text: 'The **renewal** date is May' })] });
    renderPanel(links);
    const gutter = within(rowOf('Second line'));
    const countChip = gutter.getByRole('button', { name: '2 Companion notes on this line' });
    expect(countChip).toHaveAttribute('aria-expanded', 'false');
    expect(gutter.queryByRole('list')).toBeNull();
    fireEvent.click(countChip);
    expect(countChip).toHaveAttribute('aria-expanded', 'true');
    const list = gutter.getByRole('list', { name: 'Companion notes on this line' });
    expect(within(list).getAllByRole('button').map((button) => button.textContent)).toEqual(['SuggestionNote i1', 'AnswerThe renewal date is May']);
    fireEvent.click(within(list).getByRole('button', { name: /The renewal date is May/ }));
    expect(links.showInCompanion).toHaveBeenCalledWith('i2');
    expect(gutter.queryByRole('list')).toBeNull();
  });

  it('closes the list on Escape and on a press outside it', () => {
    renderPanel(makeLinks({ items: [item('i1', 1, 5, 8), item('i2', 2, 6, 8)] }));
    const gutter = within(rowOf('Second line'));
    fireEvent.click(gutter.getByRole('button', { name: '2 Companion notes on this line' }));
    fireEvent.keyDown(gutter.getByRole('list'), { key: 'Escape' });
    expect(gutter.queryByRole('list')).toBeNull();
    fireEvent.click(gutter.getByRole('button', { name: '2 Companion notes on this line' }));
    fireEvent.pointerDown(document.body);
    expect(gutter.queryByRole('list')).toBeNull();
  });

  it('leaves out dismissed items and items that map to no line', () => {
    renderPanel(makeLinks({ items: [item('gone', 1, 5, 8, { dismissed: true }), item('far', 2, 900, 910)] }));
    expect(document.querySelector('.meeting-transcript-link-chip')).toBeNull();
  });

  it('never puts a chip on a line without timeline seconds', () => {
    renderPanel(makeLinks({ items: [item('i1', 1, 5, 8)] }));
    expect(within(rowOf('Untimed line')).queryByRole('button')).toBeNull();
  });

  it('reports hover from a chip and highlights the span of the hovered item', () => {
    const links = makeLinks({ items: [item('i1', 1, 0, 9)] });
    const view = renderPanel(links);
    const chip = within(rowOf('Second line')).getByRole('button', { name: /Show the suggestion/ });
    fireEvent.mouseEnter(chip);
    expect(links.hover).toHaveBeenCalledWith('i1');
    fireEvent.mouseLeave(chip);
    expect(links.hover).toHaveBeenLastCalledWith(null);

    view.rerenderWith({ ...links, hoveredItemId: 'i1' });
    expect(rowOf('First line')).toHaveClass('is-linked');
    expect(rowOf('Second line')).toHaveClass('is-linked');
    expect(rowOf('Third line')).not.toHaveClass('is-linked');
    expect(rowOf('First line')).not.toHaveClass('is-link-flash');
  });

  it('scrolls to and flashes the span of a transcript focus, then clears the flash', () => {
    const links = makeLinks({ items: [item('i1', 1, 5, 8)] });
    const view = renderPanel(links);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    view.rerenderWith({ ...links, transcriptFocus: { itemId: 'i1', start: 5, end: 8, key: 'local:1' } });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1);
    expect(rowOf('Second line')).toHaveClass('is-link-flash');
    expect(rowOf('First line')).not.toHaveClass('is-link-flash');

    act(() => {
      vi.advanceTimersByTime(LINK_FLASH_MS + 10);
    });
    expect(rowOf('Second line')).not.toHaveClass('is-link-flash');
    expect(rowOf('Second line')).not.toHaveClass('is-linked');

    // The same span again is a new request with a new key.
    view.rerenderWith({ ...links, transcriptFocus: { itemId: 'i1', start: 5, end: 8, key: 'local:2' } });
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(2);
    expect(rowOf('Second line')).toHaveClass('is-link-flash');
  });

  it('does nothing for a focus on a span with no lines', () => {
    const links = makeLinks({ items: [] });
    const view = renderPanel(links);
    view.rerenderWith({ ...links, transcriptFocus: { itemId: 'i1', start: 900, end: 910, key: 'local:1' } });
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    expect(document.querySelector('.is-link-flash')).toBeNull();
  });

  it('re-renders only the line whose chips changed', () => {
    const first = [item('i1', 1, 5, 8)];
    const links = makeLinks({ items: first });
    const view = renderPanel(links);
    const before = ['l1', 'l2', 'l3'].map(__getTranscriptRowRenderCountForTests);

    view.rerenderWith({ ...links, items: [...first, item('i2', 2, 10, 14)] });
    const after = ['l1', 'l2', 'l3'].map(__getTranscriptRowRenderCountForTests);
    expect(after[0]).toBe(before[0]);
    expect(after[1]).toBe(before[1]);
    expect(after[2]).toBe(before[2] + 1);
  });
});
