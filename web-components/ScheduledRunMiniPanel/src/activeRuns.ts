import type { ActiveRunItem, MiniPanelRow } from './types';

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
