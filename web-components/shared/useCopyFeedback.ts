import { useCallback, useEffect, useRef, useState } from 'react';

export const COPY_FEEDBACK_MS = 1500;

const FLAG_KEY = 'copied';

/**
 * Tracks which copy control is showing its transient "Copied" confirmation. At most one key is active at a time, flashing a second key replaces the first, and every flash restarts a single timer so an earlier flash can never clear a later one. The timer is cleared on unmount so no state update is attempted after the component is gone.
 */
export function useCopyFeedback<Key extends string = typeof FLAG_KEY>(
  durationMs: number = COPY_FEEDBACK_MS,
): { copiedKey: Key | null; flash: (key?: Key) => void } {
  const [copiedKey, setCopiedKey] = useState<Key | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  const flash = useCallback((key: Key = FLAG_KEY as Key) => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    setCopiedKey(key);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setCopiedKey(null);
    }, durationMs);
  }, [durationMs]);

  return { copiedKey, flash };
}

/**
 * Boolean form of `useCopyFeedback` for a single copy control. `flashCopied` takes no arguments so it is safe to pass directly as an event handler.
 */
export function useCopiedFlag(durationMs: number = COPY_FEEDBACK_MS): readonly [boolean, () => void] {
  const { copiedKey, flash } = useCopyFeedback(durationMs);
  const flashCopied = useCallback(() => flash(), [flash]);
  return [copiedKey !== null, flashCopied] as const;
}
