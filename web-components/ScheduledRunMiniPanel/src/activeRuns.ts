import type { ActiveRunItem, MiniPanelRow, ScheduledRunRecord } from './types';

// A row that has only just appeared may not be in the backend's active list yet, so it is not read as ended until it has been on screen this long.
export const ENDED_RUN_GRACE_MS = 10000;

/**
 * Running rows the backend no longer lists as active. A run leaves that list the moment it ends, so such a row ended while the panel was not told (a dropped connection, a missed event) and has to be settled from the run's own record.
 */
export function rowsMissingFromActive(
  rows: MiniPanelRow[],
  items: ActiveRunItem[],
  now: number = Date.now(),
): MiniPanelRow[] {
  const listed = new Set(items.map(it => it.run_id));
  return rows.filter(r => r.status === 'running' && !listed.has(r.runId) && now - r.startedAt >= ENDED_RUN_GRACE_MS);
}

/** Whether the run's record shows it has stopped, as opposed to a record read just before the run was claimed or just after it was listed. */
export function runHasEnded(run: ScheduledRunRecord): boolean {
  return run.status !== 'running' && run.status !== 'scheduled';
}

/** A run record in the shape of a ``scheduled_agent_task_run_completed`` event, so a row settled from the record is drawn exactly like one settled by the event. */
export function completionEventFromRun(run: ScheduledRunRecord): Record<string, unknown> {
  return {
    status: run.status,
    agent_task_id: run.agent_task_id ?? undefined,
    agent_task_status: run.agent_task_status ?? (run.status === 'canceled' ? 'canceled' : undefined),
    outcome: run.outcome ?? undefined,
    verification_status: run.verification_status ?? undefined,
  };
}

// The agent task's own status, outcome and verification state, which the shared run phase reads.
function taskFacts(item: ActiveRunItem): Pick<MiniPanelRow, 'taskStatus' | 'outcome' | 'verificationStatus'> {
  return {
    taskStatus: item.agent_task_status ?? undefined,
    outcome: item.outcome ?? undefined,
    verificationStatus: item.verification_status === 'pending' || item.verification_status === 'resolved' ? item.verification_status : undefined,
  };
}

export function activeItemToRow(item: ActiveRunItem): MiniPanelRow {
  return {
    runId: item.run_id,
    scheduledAgentTaskId: item.scheduled_agent_task_id,
    agentTaskId: item.agent_task_id ?? undefined,
    title: item.title,
    currentStep: 'Running…',
    status: 'running',
    ...taskFacts(item),
    startedAt: item.started_at ? Date.parse(item.started_at) : Date.now(),
    awaitingInput: item.agent_task_status === 'awaiting_user_input',
  };
}

/** Sets the live step text on the running row of one agent task; a finished row keeps the verdict it ended with, so late step text cannot replace it. */
export function withStepText(rows: MiniPanelRow[], agentTaskId: string, stepText: string): MiniPanelRow[] {
  return rows.map(r => (r.agentTaskId === agentTaskId && r.status === 'running' ? { ...r, currentStep: stepText } : r));
}

/**
 * Adds runs the panel has not seen and refreshes the backend-owned fields (approval state, agent task id) of running rows it already has; the live step text and any finished row are left untouched.
 */
export function mergeActiveItems(
  prev: MiniPanelRow[],
  items: ActiveRunItem[],
  approvalFlagHolds: ReadonlyMap<string, number> = new Map(),
  now: number = Date.now(),
): MiniPanelRow[] {
  const byRun = new Map(prev.map(r => [r.runId, r]));
  for (const it of items) {
    const existing = byRun.get(it.run_id);
    if (!existing) {
      byRun.set(it.run_id, activeItemToRow(it));
      continue;
    }
    if (existing.status !== 'running') continue;
    const held = (approvalFlagHolds.get(it.run_id) ?? 0) > now && existing.awaitingInput === true;
    const awaitingInput = held || it.agent_task_status === 'awaiting_user_input';
    const agentTaskId = existing.agentTaskId ?? it.agent_task_id ?? undefined;
    const facts = taskFacts(it);
    if (
      existing.awaitingInput === awaitingInput
      && existing.agentTaskId === agentTaskId
      && existing.taskStatus === facts.taskStatus
      && existing.outcome === facts.outcome
      && existing.verificationStatus === facts.verificationStatus
    ) continue;
    byRun.set(it.run_id, { ...existing, ...facts, awaitingInput, agentTaskId });
  }
  return Array.from(byRun.values());
}
