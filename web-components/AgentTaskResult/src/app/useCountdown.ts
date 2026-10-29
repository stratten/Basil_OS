import { useEffect, useState } from 'react';

/** Format whole seconds as m:ss, or h:mm:ss once an hour or more remains. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${rest}`;
  return `${minutes}:${rest}`;
}

function secondsUntil(targetMs: number | null): number | null {
  if (targetMs === null || !Number.isFinite(targetMs)) return null;
  return Math.max(0, Math.ceil((targetMs - Date.now()) / 1000));
}

/**
 * Whole seconds until `targetMs` (epoch milliseconds), recomputed from the wall clock every second so a throttled or resumed tab never drifts.
 * Returns null when there is no target and stops ticking once it reaches 0.
 */
export function useCountdown(targetMs: number | null): number | null {
  const [remaining, setRemaining] = useState<number | null>(() => secondsUntil(targetMs));

  useEffect(() => {
    setRemaining(secondsUntil(targetMs));
    if (targetMs === null) return undefined;
    const timer = setInterval(() => {
      const next = secondsUntil(targetMs);
      setRemaining(next);
      if (next === 0) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [targetMs]);

  return remaining;
}
