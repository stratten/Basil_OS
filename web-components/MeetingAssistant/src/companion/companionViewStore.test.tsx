import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { getCompanionView, resetCompanionViews, updateCompanionView, useCompanionView } from './companionViewStore';

beforeEach(() => resetCompanionViews());

describe('companionViewStore', () => {
  it('treats the hydrated backlog as seen the first time a meeting is shown', () => {
    const { result } = renderHook(() => useCompanionView('m1', 7));
    expect(result.current.view.lastSeenSeq).toBe(7);
  });

  it('does not overwrite what was seen when the pane remounts or re-hydrates with a higher baseline', () => {
    const first = renderHook(() => useCompanionView('m1', 7));
    act(() => first.result.current.markSeen(12));
    first.unmount();
    const second = renderHook(() => useCompanionView('m1', 20));
    expect(second.result.current.view.lastSeenSeq).toBe(12);
  });

  it('never moves the seen marker backward', () => {
    updateCompanionView('m1', { lastSeenSeq: 9 });
    updateCompanionView('m1', { lastSeenSeq: 4 });
    expect(getCompanionView('m1').lastSeenSeq).toBe(9);
  });

  it('keeps each meeting separate and gives a pane with no meeting one shared view', () => {
    const { result } = renderHook(() => useCompanionView(null, null));
    act(() => result.current.update({ composerCollapsed: true }));
    expect(result.current.view.composerCollapsed).toBe(true);
    expect(getCompanionView('a').composerCollapsed).toBe(false);
    updateCompanionView('a', { pinnedOpen: false });
    expect(getCompanionView('b').pinnedOpen).toBe(true);
  });

  it('keeps layout choices when the pane remounts', () => {
    const first = renderHook(() => useCompanionView('m1', 1));
    act(() => first.result.current.update({ settingsOpen: true, composerCollapsed: true }));
    first.unmount();
    const second = renderHook(() => useCompanionView('m1', 1));
    expect(second.result.current.view).toMatchObject({ settingsOpen: true, composerCollapsed: true });
  });
});
