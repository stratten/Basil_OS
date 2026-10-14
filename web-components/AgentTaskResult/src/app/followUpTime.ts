const SOON_TEXT = 'soon';

export interface FollowUpDueDescription {
  /** True once the scheduled time has passed and Basil is about to start the check. */
  isDue: boolean;
  /** Compact phrase for a sidebar row, e.g. "Checks again 3:15 PM". */
  rowText: string;
  /** Full sentence for the result view, e.g. "Basil will check again automatically at 3:15 PM." */
  sentence: string;
}

function isSameLocalDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

export function describeFollowUpDue(dueAt: string, now: Date = new Date()): FollowUpDueDescription | null {
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;
  if (due.getTime() <= now.getTime()) {
    return {
      isDue: true,
      rowText: `Checking again ${SOON_TEXT}`,
      sentence: 'Basil is about to check again.',
    };
  }
  const when = isSameLocalDay(due, now)
    ? due.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : due.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  return {
    isDue: false,
    rowText: `Checks again ${when}`,
    sentence: `Basil will check again automatically at ${when}.`,
  };
}
