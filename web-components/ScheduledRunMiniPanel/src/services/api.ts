import type { ActiveRunItem } from '../types';

let baseUrl = 'http://localhost:8000';

const AGENT_TASK_RUNS_API_PREFIX = '/api/v1/agent-task-runs';

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
