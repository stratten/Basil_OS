import type { ActiveRunItem, ScheduledRunRecord } from '../types';

let baseUrl = 'http://localhost:8000';

const AGENT_TASK_RUNS_API_PREFIX = '/api/v1/agent-task-runs';
const AGENT_TASK_SCHEDULES_API_PREFIX = '/api/v1/agent-task-schedules';
// A schedule's most recent runs; a run that just left the active list is among the newest.
const RECENT_RUN_LIMIT = 20;

export function setBaseUrl(port: number) {
  baseUrl = `http://localhost:${port}`;
}

export async function fetchActiveScheduledRuns(): Promise<ActiveRunItem[]> {
  const resp = await fetch(
    `${baseUrl}${AGENT_TASK_RUNS_API_PREFIX}/active`
  );
  if (!resp.ok) {
    throw new Error(`Failed to fetch active scheduled runs: HTTP ${resp.status}`);
  }
  return await resp.json() as ActiveRunItem[];
}

/**
 * One run's record from its schedule's recent runs, or null when the backend no longer lists it.
 * Used when a run leaves the active list without the panel having heard it finish.
 */
export async function fetchScheduledRun(scheduledAgentTaskId: string, runId: string): Promise<ScheduledRunRecord | null> {
  const resp = await fetch(
    `${baseUrl}${AGENT_TASK_SCHEDULES_API_PREFIX}/${encodeURIComponent(scheduledAgentTaskId)}/runs?limit=${RECENT_RUN_LIMIT}`
  );
  if (!resp.ok) {
    throw new Error(`Failed to fetch runs of scheduled task ${scheduledAgentTaskId}: HTTP ${resp.status}`);
  }
  const runs = await resp.json() as ScheduledRunRecord[];
  return runs.find(run => run.id === runId) ?? null;
}
