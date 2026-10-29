import { useState } from 'react';
import NativeSymbolIcon from '@shared/NativeSymbolIcon';
import { describeFollowUpDue } from '../../app/followUpTime';
import { formatCountdown, useCountdown } from '../../app/useCountdown';

/** A scheduled follow-up shows a live countdown only when it is this close; farther out, the clock time reads better. */
export const SCHEDULED_COUNTDOWN_WINDOW_SECONDS = 15 * 60;

interface FollowUpWaitingNoticeProps {
  /** ISO due time of this task's soonest scheduled follow-up check. */
  dueAt?: string;
  /** Epoch milliseconds at which a wait inside the running task ends. Takes precedence over `dueAt`. */
  resumeAtMs?: number;
  /** Why the task is waiting, shown under the countdown for in-run waits. */
  reason?: string;
  /** Stops the scheduled checks. Offered only for a scheduled follow-up, never for a wait inside the running task. */
  onStopChecking?: () => Promise<void>;
}

function dueAtMs(dueAt: string | undefined): number | null {
  if (!dueAt) return null;
  const parsed = new Date(dueAt).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

/** Tells the user this task is not finished and shows how long until Basil checks again. */
export function FollowUpWaitingNotice({ dueAt, resumeAtMs, reason, onStopChecking }: FollowUpWaitingNoticeProps) {
  const [stopState, setStopState] = useState<'idle' | 'stopping' | 'failed'>('idle');
  const inRun = typeof resumeAtMs === 'number' && Number.isFinite(resumeAtMs);
  const targetMs = inRun ? resumeAtMs : dueAtMs(dueAt);
  const remaining = useCountdown(targetMs);
  const due = !inRun && dueAt ? describeFollowUpDue(dueAt) : null;
  if (targetMs === null || remaining === null) return null;
  if (!inRun && !due) return null;

  const showCountdown = inRun || remaining <= SCHEDULED_COUNTDOWN_WINDOW_SECONDS;
  const title = showCountdown
    ? (remaining > 0 ? `Checking again in ${formatCountdown(remaining)}` : 'Checking now')
    : 'Waiting to check again';
  const detail = showCountdown ? (reason?.trim() || null) : (due?.sentence ?? null);
  const canStop = !inRun && typeof onStopChecking === 'function';

  async function stopChecking() {
    if (!onStopChecking || stopState === 'stopping') return;
    setStopState('stopping');
    try {
      await onStopChecking();
      setStopState('idle');
    } catch {
      setStopState('failed');
    }
  }

  return (
    <div
      className="execution-activity-dock run-status-card--live follow-up-waiting-notice"
      role="status"
      data-testid="follow-up-waiting-notice"
    >
      <span className="follow-up-waiting-notice__icon">
        <NativeSymbolIcon name="refresh" size={14} />
      </span>
      <span className="follow-up-waiting-notice__text">
        <span className="follow-up-waiting-notice__title">{title}</span>
        {detail && <span className="follow-up-waiting-notice__detail">{detail}</span>}
        {stopState === 'failed' && (
          <span className="follow-up-waiting-notice__error" role="alert">Could not stop the scheduled check. Try again.</span>
        )}
      </span>
      {canStop && (
        <button
          type="button"
          className="follow-up-waiting-notice__stop"
          data-testid="follow-up-stop-checking"
          disabled={stopState === 'stopping'}
          onClick={() => void stopChecking()}
        >
          {stopState === 'stopping' ? 'Stopping…' : 'Stop checking'}
        </button>
      )}
    </div>
  );
}
