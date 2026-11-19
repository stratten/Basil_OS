import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useLastChecked } from './useLastChecked';

describe('useLastChecked', () => {
  it('is null until the Companion has been seen to finish looking', () => {
    const { result, rerender } = renderHook(({ evaluating }) => useLastChecked(evaluating), { initialProps: { evaluating: false } });
    expect(result.current).toBeNull();
    rerender({ evaluating: true });
    expect(result.current).toBeNull();
  });

  it('records the moment evaluating goes from true to false, and keeps it until the next one', () => {
    const times = [new Date(2026, 9, 16, 10, 0, 1), new Date(2026, 9, 16, 10, 0, 31)];
    let call = 0;
    const clock = () => times[Math.min(call++, times.length - 1)];
    const { result, rerender } = renderHook(({ evaluating }) => useLastChecked(evaluating, clock), { initialProps: { evaluating: false } });
    rerender({ evaluating: true });
    act(() => rerender({ evaluating: false }));
    expect(result.current).toEqual(times[0]);
    rerender({ evaluating: false });
    expect(result.current).toEqual(times[0]);
    rerender({ evaluating: true });
    rerender({ evaluating: false });
    expect(result.current).toEqual(times[1]);
  });

  it('does not treat a pane that mounts mid-evaluation as a finished check', () => {
    const { result } = renderHook(() => useLastChecked(true));
    expect(result.current).toBeNull();
  });
});
