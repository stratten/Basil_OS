import type {
  CompanionFeedbackAction,
  CompanionGlobalSettings,
  CompanionItemAction,
  CompanionItemActionResult,
  CompanionMode,
  CompanionProposalDecision,
  CompanionProposalResult,
  CompanionRoot,
  CompanionSnapshot,
  CompanionStatus,
  CompanionWatch,
} from './types';

export class CompanionApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'CompanionApiError';
    this.status = status;
  }
}

export function companionBaseUrl(port: number): string {
  return `http://127.0.0.1:${port}`;
}

export function companionSocketUrl(port: number): string {
  return `ws://127.0.0.1:${port}/ws`;
}

async function readDetail(response: Response): Promise<string> {
  const fallback = `The request failed (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string' && detail.trim() !== '') return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0];
        if (typeof first === 'object' && first !== null && 'msg' in first && typeof (first as { msg: unknown }).msg === 'string') {
          return (first as { msg: string }).msg;
        }
      }
    }
  } catch {
    // A non-JSON error body falls through to the generic message.
  }
  return fallback;
}

async function request<T>(port: number, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${companionBaseUrl(port)}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    });
  } catch {
    throw new CompanionApiError(0, 'Basil could not reach its backend. Check that it is running.');
  }
  if (!response.ok) {
    throw new CompanionApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

function meetingPath(meetingId: string): string {
  return `/meetings/${encodeURIComponent(meetingId)}/companion`;
}

export function fetchGlobalSettings(port: number): Promise<CompanionGlobalSettings> {
  return request<CompanionGlobalSettings>(port, '/meetings/companion/settings');
}

export function updateGlobalSettings(port: number, body: Partial<CompanionGlobalSettings>): Promise<CompanionGlobalSettings> {
  return request<CompanionGlobalSettings>(port, '/meetings/companion/settings', { method: 'PUT', body: JSON.stringify(body) });
}

export function fetchSnapshot(port: number, meetingId: string): Promise<CompanionSnapshot> {
  return request<CompanionSnapshot>(port, meetingPath(meetingId));
}

export function enableCompanion(
  port: number,
  meetingId: string,
  body: { model_id: string | null; mode?: CompanionMode },
): Promise<CompanionSnapshot> {
  return request<CompanionSnapshot>(port, `${meetingPath(meetingId)}/enable`, { method: 'POST', body: JSON.stringify(body) });
}

export function disableCompanion(port: number, meetingId: string): Promise<CompanionSnapshot> {
  return request<CompanionSnapshot>(port, `${meetingPath(meetingId)}/disable`, { method: 'POST', body: '{}' });
}

export function patchCompanionSettings(
  port: number,
  meetingId: string,
  body: { model_id?: string | null; mode?: CompanionMode; focus?: string; investigate?: boolean },
): Promise<CompanionStatus> {
  return request<CompanionStatus>(port, `${meetingPath(meetingId)}/settings`, { method: 'PATCH', body: JSON.stringify(body) });
}

export function attachCompanionRoot(port: number, meetingId: string, path: string): Promise<CompanionRoot> {
  return request<CompanionRoot>(port, `${meetingPath(meetingId)}/roots`, { method: 'POST', body: JSON.stringify({ path }) });
}

export function detachCompanionRoot(port: number, meetingId: string, rootId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(port, `${meetingPath(meetingId)}/roots/${encodeURIComponent(rootId)}`, { method: 'DELETE' });
}

export function sendCompanionFeedback(
  port: number,
  meetingId: string,
  itemId: string,
  action: CompanionFeedbackAction,
): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(port, `${meetingPath(meetingId)}/items/${encodeURIComponent(itemId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

export function decideCompanionProposal(
  port: number,
  meetingId: string,
  itemId: string,
  decision: CompanionProposalDecision,
): Promise<CompanionProposalResult> {
  return request<CompanionProposalResult>(port, `${meetingPath(meetingId)}/items/${encodeURIComponent(itemId)}/proposal`, {
    method: 'POST',
    body: JSON.stringify({ decision }),
  });
}

/** The user's own click: makes a to-do or hands an agent the note, creating an action card and approving it in one step. */
export function actOnCompanionItem(port: number, meetingId: string, itemId: string, action: CompanionItemAction): Promise<CompanionItemActionResult> {
  return request<CompanionItemActionResult>(port, `${meetingPath(meetingId)}/items/${encodeURIComponent(itemId)}/action`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

/** Starts an audit in the background; the report arrives as an `audit` timeline event and `status.auditing` shows it running. */
export function startCompanionAudit(port: number, meetingId: string): Promise<{ started: boolean }> {
  return request<{ started: boolean }>(port, `${meetingPath(meetingId)}/audit`, { method: 'POST' });
}

/** `replyToMessageId` names the chat message the question came from, so the researched answer can quote it. */
export function startCompanionInvestigation(port: number, meetingId: string, question: string, replyToMessageId?: string): Promise<{ investigation_id: string }> {
  return request<{ investigation_id: string }>(port, `${meetingPath(meetingId)}/investigations`, {
    method: 'POST',
    body: JSON.stringify(replyToMessageId ? { question, reply_to_message_id: replyToMessageId } : { question }),
  });
}

export function cancelCompanionInvestigation(port: number, meetingId: string, investigationId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(port, `${meetingPath(meetingId)}/investigations/${encodeURIComponent(investigationId)}`, { method: 'DELETE' });
}

export function sendCompanionChat(port: number, meetingId: string, text: string): Promise<{ message_id: string }> {
  return request<{ message_id: string }>(port, `${meetingPath(meetingId)}/chat`, { method: 'POST', body: JSON.stringify({ text }) });
}

export function createCompanionWatch(
  port: number,
  meetingId: string,
  topic: string,
  instruction: string,
): Promise<CompanionWatch> {
  return request<CompanionWatch>(port, `${meetingPath(meetingId)}/watches`, {
    method: 'POST',
    body: JSON.stringify({ topic, instruction }),
  });
}

export function cancelCompanionWatch(port: number, meetingId: string, watchId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(port, `${meetingPath(meetingId)}/watches/${encodeURIComponent(watchId)}`, { method: 'DELETE' });
}
