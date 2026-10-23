import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useStableReadonlySet } from './useStableReadonlySet';

describe('useStableReadonlySet', () => {
  it('returns the same reference across renders when set membership is unchanged', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: ReadonlySet<string> }) => useStableReadonlySet(value),
      { initialProps: { value: new Set(['a', 'b']) } },
    );
    const first = result.current;
    rerender({ value: new Set(['b', 'a']) });
    expect(result.current).toBe(first);
  });

  it('returns a new reference when set membership actually changes', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: ReadonlySet<string> }) => useStableReadonlySet(value),
      { initialProps: { value: new Set(['a']) } },
    );
    const first = result.current;
    const changed = new Set(['a', 'b']);
    rerender({ value: changed });
    expect(result.current).toBe(changed);
    expect(result.current).not.toBe(first);
  });

  it('treats repeated empty sets as stable', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: ReadonlySet<string> }) => useStableReadonlySet(value),
      { initialProps: { value: new Set<string>() } },
    );
    const first = result.current;
    rerender({ value: new Set<string>() });
    expect(result.current).toBe(first);
  });
});
