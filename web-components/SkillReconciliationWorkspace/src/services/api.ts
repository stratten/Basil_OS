import type {
  ActionDecision,
  ActionEditFields,
  ProposedAction,
  ReconciliationSession,
} from '../types';

async function request<T>(apiBaseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

const BASE = '/memory/reconciliation';

export function startSession(apiBaseUrl: string) {
  return request<ReconciliationSession>(apiBaseUrl, `${BASE}/session`, { method: 'POST' });
}

export function getSession(apiBaseUrl: string) {
  return request<ReconciliationSession>(apiBaseUrl, `${BASE}/session`);
}

export function decideAction(
  apiBaseUrl: string,
  actionId: string,
  decision: ActionDecision,
  edited?: ActionEditFields,
) {
  return request<ProposedAction>(
    apiBaseUrl,
    `${BASE}/session/actions/${encodeURIComponent(actionId)}/decision`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, edited: edited ?? null }),
    },
  );
}

export function commitSession(apiBaseUrl: string) {
  return request<ReconciliationSession>(apiBaseUrl, `${BASE}/session/commit`, { method: 'POST' });
}

export function discardSession(apiBaseUrl: string) {
  return request<{ discarded: boolean }>(apiBaseUrl, `${BASE}/session/discard`, { method: 'POST' });
}
