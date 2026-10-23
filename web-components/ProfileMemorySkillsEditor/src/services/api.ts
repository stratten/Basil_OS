import type { AgentTaskSummary, MemoryCapsResponse, MemoryDocument, MemoryProposal, SkillCandidate, SkillRecord } from '../types';

export class ProfileEditorApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ProfileEditorApiError';
  }
}

async function request<T>(apiBaseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const responseBody = await response.text();
    let message = responseBody;
    try {
      const payload: unknown = JSON.parse(responseBody);
      if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
        const detail = payload.detail;
        if (typeof detail === 'object' && detail !== null && 'message' in detail && typeof detail.message === 'string') {
          message = detail.message;
        } else if (typeof detail === 'string') {
          message = detail;
        }
      }
    } catch {
      // Preserve a non-JSON response body as the user-safe fallback message.
    }
    throw new ProfileEditorApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export function getMemoryDocument(apiBaseUrl: string, fileName: string) {
  return request<MemoryDocument>(apiBaseUrl, `/memory/${encodeURIComponent(fileName)}`);
}

export function updateMemoryDocument(apiBaseUrl: string, fileName: string, content: string) {
  return request<MemoryDocument>(apiBaseUrl, `/memory/${encodeURIComponent(fileName)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export async function getMemoryCap(apiBaseUrl: string, fileName: string) {
  const response = await request<MemoryCapsResponse>(apiBaseUrl, '/memory/caps');
  return response.caps[fileName] ?? null;
}

export async function getMemoryProposal(apiBaseUrl: string, id: string) {
  const response = await request<{ proposals: MemoryProposal[] }>(apiBaseUrl, '/memory/promotions');
  return response.proposals.find((proposal) => proposal.id === id) ?? null;
}

export function approveMemoryProposal(apiBaseUrl: string, id: string, editedEntry: string, targetFileName?: string) {
  return request<MemoryProposal>(apiBaseUrl, `/memory/promotions/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ edited_entry: editedEntry, target_file_name: targetFileName }),
  });
}

export function declineMemoryProposal(apiBaseUrl: string, id: string) {
  return request<MemoryProposal>(apiBaseUrl, `/memory/promotions/${encodeURIComponent(id)}/decline`, {
    method: 'POST',
  });
}

export function getSkill(apiBaseUrl: string, slug: string) {
  return request<SkillRecord>(apiBaseUrl, `/memory/skills/${encodeURIComponent(slug)}`);
}

export function updateSkill(apiBaseUrl: string, slug: string, skill: Pick<SkillRecord, 'title' | 'body' | 'when_to_use' | 'triggers'>) {
  return request<SkillRecord>(apiBaseUrl, `/memory/skills/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(skill),
  });
}

export function deleteSkill(apiBaseUrl: string, slug: string) {
  return request<{ deleted: boolean }>(apiBaseUrl, `/memory/skills/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  });
}

export async function getSkillCandidate(apiBaseUrl: string, id: string) {
  const response = await request<{ candidates: SkillCandidate[] }>(apiBaseUrl, '/memory/skill-candidates');
  return response.candidates.find((candidate) => candidate.id === id) ?? null;
}

export function approveSkillCandidate(apiBaseUrl: string, id: string, candidate: Partial<SkillCandidate>) {
  return request<SkillCandidate>(apiBaseUrl, `/memory/skill-candidates/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify(candidate),
  });
}

export function declineSkillCandidate(apiBaseUrl: string, id: string) {
  return request<SkillCandidate>(apiBaseUrl, `/memory/skill-candidates/${encodeURIComponent(id)}/decline`, {
    method: 'POST',
  });
}

export function getAgentTaskSummary(apiBaseUrl: string, id: string) {
  return request<AgentTaskSummary>(apiBaseUrl, `/api/v1/agent-tasks/${encodeURIComponent(id)}`);
}
