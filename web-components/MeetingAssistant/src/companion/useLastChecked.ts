import { useEffect, useRef, useState } from 'react';

/** When the Companion last finished looking at the conversation, taken from `evaluating` going from true to false while this pane is open. Null until it has been seen to happen, so no time is ever invented. The backend sends no such field, so this is the client's own observation. */
export function useLastChecked(evaluating: boolean, now: () => Date = () => new Date()): Date | null {
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const wasEvaluating = useRef(evaluating);
  const clock = useRef(now);
  clock.current = now;

  useEffect(() => {
    if (wasEvaluating.current && !evaluating) setCheckedAt(clock.current());
    wasEvaluating.current = evaluating;
  }, [evaluating]);

  return checkedAt;
}
