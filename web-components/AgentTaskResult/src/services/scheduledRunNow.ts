import * as api from './api';

export interface ScheduledRunNowOutcome {
  ok: boolean;
  /** Plain-language reason when the run did not start. */
  message?: string;
}

const COULD_NOT_START = 'Basil could not start this run. Try again.';

/**
 * Starts a schedule's run immediately and reports whether it started.
 *
 * The backend answers a failed start with a normal response whose `success` is false, so a caller that only awaits the request would never see the failure. This turns both that response and a thrown error into one outcome the sidebar row and the schedule's own view can show.
 */
export async function startScheduledRunNow(scheduledAgentTaskId: string): Promise<ScheduledRunNowOutcome> {
  try {
    const result = await api.runScheduledAgentTaskNow(scheduledAgentTaskId);
    if (result.success) return { ok: true };
    return { ok: false, message: result.error?.trim() || COULD_NOT_START };
  } catch (error) {
    return { ok: false, message: error instanceof Error && error.message.trim() ? error.message : COULD_NOT_START };
  }
}
