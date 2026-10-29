import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingFocusRequestDTO, TranscriptLineDTO } from '../bridge/types';

const focusTranscript = vi.hoisted(() => vi.fn());
const focusCompanionItem = vi.hoisted(() => vi.fn());
vi.mock('../bridge/meetingBridge', () => ({ focusTranscript, focusCompanionItem }));

import { useCompanionLinksValue } from './companionLinks';
import type { CompanionItem } from './types';

const line = (id: string, start: number, end: number): TranscriptLineDTO => ({
  id, text: id, speakerId: null, isInterim: false, displayStart: null, timelineStartSeconds: start, timelineEndSeconds: end, source: null, lineComplete: true,
});

const item = (id: string, start: number, end: number): CompanionItem => ({
  id, seq: 1, kind: 'insight', text: id, confidence: 0.5, citations: [], no_source: false,
  transcript_range: { start, end, turn_ids: [] }, trigger: 'periodic', watch_id: null, truncated: false, pinned: false, dismissed: false,
});

const transcript = [line('a', 0, 4), line('b', 5, 9)];

type Options = Parameters<typeof useCompanionLinksValue>[0];
const baseOptions: Options = { role: 'notetaker', transcript, items: [item('i1', 5, 8)], focusRequest: null };

function render(options: Partial<Options> = {}) {
  return renderHook((props: Options) => useCompanionLinksValue(props), { initialProps: { ...baseOptions, ...options } });
}

const request = (overrides: Partial<MeetingFocusRequestDTO>): MeetingFocusRequestDTO => ({ target: 'transcript', itemId: 'i1', startSeconds: 5, endSeconds: 8, nonce: 1, ...overrides });

describe('useCompanionLinksValue', () => {
  beforeEach(() => {
    focusTranscript.mockReset();
    focusCompanionItem.mockReset();
  });

  it('only offers a transcript link for an item that maps to a line', () => {
    const { result } = render();
    expect(result.current.canShowInTranscript(item('x', 5, 8))).toBe(true);
    expect(result.current.canShowInTranscript(item('far', 500, 510))).toBe(false);
  });

  it('answers a card click in the Notetaker window locally, with a fresh key each time', () => {
    const { result } = render();
    act(() => result.current.showInTranscript(item('i1', 8, 5)));
    expect(result.current.transcriptFocus).toMatchObject({ itemId: 'i1', start: 5, end: 8 });
    const firstKey = result.current.transcriptFocus?.key;
    act(() => result.current.showInTranscript(item('i1', 5, 8)));
    expect(result.current.transcriptFocus?.key).not.toBe(firstKey);
    expect(focusTranscript).not.toHaveBeenCalled();
  });

  it('asks the Notetaker window from the detached Companion window', () => {
    const { result } = render({ role: 'companion' });
    act(() => result.current.showInTranscript(item('i1', 5, 8)));
    expect(focusTranscript).toHaveBeenCalledWith('i1', 5, 8);
    expect(result.current.transcriptFocus).toBeNull();
  });

  it('answers a transcript chip locally and reveals the embedded pane when it exists', () => {
    const reveal = vi.fn();
    const { result } = render({ embeddedPane: { available: true, reveal } });
    act(() => result.current.showInCompanion('i1'));
    expect(reveal).toHaveBeenCalledTimes(1);
    expect(result.current.companionFocus).toMatchObject({ itemId: 'i1' });
    expect(focusCompanionItem).not.toHaveBeenCalled();
  });

  it('asks the detached Companion window when the Notetaker has no embedded pane', () => {
    const { result } = render({ embeddedPane: { available: false, reveal: vi.fn() } });
    act(() => result.current.showInCompanion('i1'));
    expect(focusCompanionItem).toHaveBeenCalledWith('i1');
    expect(result.current.companionFocus).toBeNull();
  });

  it('acts on a native transcript request in the Notetaker window and once per nonce', () => {
    const { result, rerender } = render();
    rerender({ ...baseOptions, focusRequest: request({ nonce: 1 }) });
    expect(result.current.transcriptFocus).toMatchObject({ itemId: 'i1', start: 5, end: 8, key: 'bridge:1' });
    // The same request delivered again (a replay after a snapshot) changes nothing.
    const first = result.current.transcriptFocus;
    rerender({ ...baseOptions, focusRequest: request({ nonce: 1 }) });
    expect(result.current.transcriptFocus).toBe(first);
    // Asking for the same span again is a new request.
    rerender({ ...baseOptions, focusRequest: request({ nonce: 2 }) });
    expect(result.current.transcriptFocus?.key).toBe('bridge:2');
  });

  it('ignores a request for a surface it does not own', () => {
    const notetaker = render();
    notetaker.rerender({ ...baseOptions, focusRequest: request({ target: 'companion', startSeconds: undefined, endSeconds: undefined }) });
    expect(notetaker.result.current.companionFocus).toBeNull();
    expect(notetaker.result.current.transcriptFocus).toBeNull();

    const detached = render({ role: 'companion' });
    detached.rerender({ ...baseOptions, role: 'companion', focusRequest: request({ nonce: 3 }) });
    expect(detached.result.current.transcriptFocus).toBeNull();
    detached.rerender({ ...baseOptions, role: 'companion', focusRequest: request({ target: 'companion', nonce: 4 }) });
    expect(detached.result.current.companionFocus).toMatchObject({ itemId: 'i1', key: 'bridge:4' });
  });

  it('ignores a transcript request that carries no range', () => {
    const { result, rerender } = render();
    rerender({ ...baseOptions, focusRequest: request({ startSeconds: undefined, endSeconds: undefined }) });
    expect(result.current.transcriptFocus).toBeNull();
  });

  it('does not replay a request that was already present when the window opened', () => {
    const { result } = render({ focusRequest: request({ nonce: 7 }) });
    expect(result.current.transcriptFocus).toBeNull();
  });

  it('tracks the hovered item', () => {
    const { result } = render();
    act(() => result.current.hover('i1'));
    expect(result.current.hoveredItemId).toBe('i1');
    act(() => result.current.hover(null));
    expect(result.current.hoveredItemId).toBeNull();
  });
});
