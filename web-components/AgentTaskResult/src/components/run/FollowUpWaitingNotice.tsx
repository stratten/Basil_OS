import NativeSymbolIcon from '@shared/NativeSymbolIcon';
import { describeFollowUpDue } from '../../app/followUpTime';

interface FollowUpWaitingNoticeProps {
  /** ISO due time of this task's soonest scheduled follow-up check. */
  dueAt: string;
}

/** Tells the user this task is not finished: Basil scheduled a follow-up check and will resume it automatically. */
export function FollowUpWaitingNotice({ dueAt }: FollowUpWaitingNoticeProps) {
  const due = describeFollowUpDue(dueAt);
  if (!due) return null;
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
        <span className="follow-up-waiting-notice__title">Waiting to check again</span>
        <span className="follow-up-waiting-notice__detail">{due.sentence}</span>
      </span>
    </div>
  );
}
