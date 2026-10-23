import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useAssistantSessionMeter } from './useAssistantSessionMeter';

describe('useAssistantSessionMeter', () => {
  it('starts at zero and updates when the bridge dispatches a meter event', () => {
    const { result } = renderHook(() => useAssistantSessionMeter());
    expect(result.current).toBe(0);

    act(() => {
      window.basilAssistantSession?.onEvent({ type: 'meter', audioLevel: 0.62 });
    });

    expect(result.current).toBe(0.62);
  });

  it('stops updating after unmount', () => {
    const { result, unmount } = renderHook(() => useAssistantSessionMeter());
    unmount();

    act(() => {
      window.basilAssistantSession?.onEvent({ type: 'meter', audioLevel: 0.9 });
    });

    expect(result.current).toBe(0);
  });
});
