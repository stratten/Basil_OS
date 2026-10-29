import { useEffect, useState } from 'react';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import type { ResponseTimeLimit } from '../../types';
import {
  responseCountdownState,
  responseTimeoutSentences,
  secondsUntilDeadline,
} from './responseTimeLimit';

/** Seconds left until `deadlineMs`, re-read four times a second and re-rendered only when the whole second changes. Stops once it reaches zero. */
export function useSecondsRemaining(deadlineMs: number): number {
  const [remaining, setRemaining] = useState(() => secondsUntilDeadline(deadlineMs, Date.now()));
  useEffect(() => {
    const read = () => {
      const next = secondsUntilDeadline(deadlineMs, Date.now());
      setRemaining(next);
      return next;
    };
    if (read() <= 0) return undefined;
    const timer = window.setInterval(() => {
      if (read() <= 0) window.clearInterval(timer);
    }, 250);
    return () => window.clearInterval(timer);
  }, [deadlineMs]);
  return remaining;
}

interface ResponseCountdownProps {
  timeLimit: ResponseTimeLimit;
  /** `inline` drops the box so the countdown can sit inside a turn that is already styled as waiting. */
  variant?: 'card' | 'inline';
}

/** Counts down to the moment Basil stops waiting for a response and says what it will do then. */
export default function ResponseCountdown({ timeLimit, variant = 'card' }: ResponseCountdownProps) {
  const secondsLeft = useSecondsRemaining(timeLimit.deadlineMs);
  const state = responseCountdownState(secondsLeft, timeLimit.limitSeconds);
  const sentences = responseTimeoutSentences(timeLimit.onTimeout);
  const clock = formatClockSeconds(secondsLeft);
  const fraction = Math.min(1, secondsLeft / timeLimit.limitSeconds);

  return (
    <div
      className={`response-countdown response-countdown--${variant} is-${state}`}
      role="timer"
      aria-label={`Time left to respond: ${clock}`}
      data-response-countdown-state={state}
    >
      <div className="response-countdown-row">
        <span className="response-countdown-clock" aria-hidden="true">{clock}</span>
        <span className="response-countdown-text" aria-live="polite">
          {state === 'expired' ? sentences.expired : sentences.pending}
        </span>
      </div>
      <div className="response-countdown-track" aria-hidden="true">
        {/* The drained share is the one genuinely dynamic value here, so it is the only inline style. */}
        <div className="response-countdown-fill" style={{ transform: `scaleX(${fraction})` }} />
      </div>
    </div>
  );
}
