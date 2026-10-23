import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { emptyTimelineState } from './companionReducer';
import { initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import { resetCompanionViews, updateCompanionView } from './companionViewStore';
import { awarenessBadgeText, useCompanionAwareness } from './useCompanionUnseen';
import type { CompanionItem } from './types';

function item(id: string, seq: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id, seq, kind: 'insight', text: id, confidence: 0.5, citations: [], no_source: false,
    transcript_range: { start: 0, end: 1, turn_ids: [] }, trigger: 'periodic', watch_id: null,
    truncated: false, pinned: false, dismissed: false, ...overrides,
  };
}

function ready(items: CompanionItem[], baselineSeq: number): CompanionStoreState {
  return { ...initialCompanionStoreState, phase: 'ready', baselineSeq, timeline: { ...emptyTimelineState, items } };
}

beforeEach(() => resetCompanionViews());

describe('useCompanionAwareness', () => {
  it('reports nothing before the Companion has loaded', () => {
    const { result } = renderHook(() => useCompanionAwareness('m', initialCompanionStoreState));
    expect(result.current).toEqual({ unseenCount: 0, decisionCount: 0 });
  });

  it('does not report the backlog of a freshly opened meeting', () => {
    const { result } = renderHook(() => useCompanionAwareness('m', ready([item('a', 1), item('b', 2)], 2)));
    expect(result.current.unseenCount).toBe(0);
  });

  it('counts what arrived after the reader last saw the stream, and updates as they read', () => {
    const state = ready([item('a', 1), item('b', 2), item('c', 3)], 0);
    const { result } = renderHook(() => useCompanionAwareness('m', state));
    expect(result.current.unseenCount).toBe(3);
    act(() => updateCompanionView('m', { lastSeenSeq: 2 }));
    expect(result.current.unseenCount).toBe(1);
    act(() => updateCompanionView('m', { lastSeenSeq: 3 }));
    expect(result.current.unseenCount).toBe(0);
  });

  it('counts proposals that still need a decision, and prefers them in the badge text', () => {
    const proposal = item('p', 2, {
      kind: 'proposal',
      proposal: { proposal_id: 'pr', action: 'todo', title: 't', instruction: 'i', authority: 'review', state: 'proposed', todo_id: null, agent_task_id: null, error: null, auto_started: false },
    });
    const { result } = renderHook(() => useCompanionAwareness('m', ready([item('a', 1), proposal], 2)));
    expect(result.current.decisionCount).toBe(1);
    expect(awarenessBadgeText({ unseenCount: 4, decisionCount: 1 })).toBe('1 to decide');
    expect(awarenessBadgeText({ unseenCount: 4, decisionCount: 0 })).toBe('4 new');
    expect(awarenessBadgeText({ unseenCount: 0, decisionCount: 0 })).toBeNull();
  });
});
