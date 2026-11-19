import { useEffect, useState } from 'react';
import type { AutoEndCountdownDTO } from '../bridge/types';
import { dismissAutoEnd } from '../bridge/meetingBridge';
import { CancelCircleIcon } from './MeetingIcons';

/** If the stop has not happened this long after its deadline, the backend probably went away; the countdown would only be stale, so it is hidden. */
const STALE_AFTER_DEADLINE_MS = 20_000;
const TICK_MS = 250;

interface AutoEndCountdownProps {
  countdown: AutoEndCountdownDTO;
}

/** Counts down to the automatic end of a detected meeting and lets the user keep recording instead. */
export default function AutoEndCountdown({ countdown }: AutoEndCountdownProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [countdown.deadlineEpochMs]);

  const remainingMs = countdown.deadlineEpochMs - now;
  if (remainingMs < -STALE_AFTER_DEADLINE_MS) return null;

  const totalMs = Math.max(countdown.totalSeconds * 1000, 1);
  const fractionLeft = Math.min(1, Math.max(0, remainingMs / totalMs));
  const secondsLeft = Math.max(0, Math.ceil(remainingMs / 1000));
  const headline = secondsLeft > 0 ? `Ending in ${secondsLeft}s` : 'Ending now';

  return (
    <div className="meeting-auto-end" role="group" aria-label="Automatic end">
      <div className="meeting-auto-end-row">
        <div className="meeting-auto-end-text">
          <span className="meeting-auto-end-headline" role="timer">{headline}</span>
          <span className="meeting-auto-end-detail">The call audio has stopped, so this recording will end on its own.</span>
        </div>
        <button type="button" className="meeting-record-button" onClick={dismissAutoEnd}>
          <CancelCircleIcon />
          Keep Recording
        </button>
      </div>
      <div
        className="meeting-auto-end-bar"
        role="progressbar"
        aria-label="Time until this recording ends"
        aria-valuemin={0}
        aria-valuemax={Math.round(countdown.totalSeconds)}
        aria-valuenow={Math.min(Math.round(countdown.totalSeconds), secondsLeft)}
        aria-valuetext={headline}
      >
        <span className="meeting-auto-end-bar-fill" style={{ transform: `scaleX(${fractionLeft})` }} />
      </div>
    </div>
  );
}
