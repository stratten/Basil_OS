import { companionBaseUrl, companionSocketUrl } from '../companion/companionApi';
import {
  parseCloudCheckResult,
  parseCloudTranscriptionState,
  type CloudCheckResult,
  type CloudProviderId,
  type CloudSettingsPatch,
  type CloudTranscriptionState,
} from './cloudTranscriptionTypes';

export const cloudTranscriptionSocketUrl = companionSocketUrl;

export class CloudApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'CloudApiError';
    this.status = status;
  }
}

async function readDetail(response: Response): Promise<string> {
  const fallback = `The request failed (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string' && detail.trim() !== '') return detail;
    }
  } catch {
    // An unreadable error body falls back to the status line.
  }
  return fallback;
}

async function request(port: number, path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(`${companionBaseUrl(port)}/meetings/cloud-transcription${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new CloudApiError(response.status, await readDetail(response));
  return response.json();
}

async function requestState(port: number, path: string, init: RequestInit = {}): Promise<CloudTranscriptionState> {
  const state = parseCloudTranscriptionState(await request(port, path, init));
  if (state === null) throw new Error('The cloud transcription response was not understood.');
  return state;
}

export function fetchCloudTranscription(port: number): Promise<CloudTranscriptionState> {
  return requestState(port, '');
}

export function updateCloudSettings(port: number, patch: CloudSettingsPatch): Promise<CloudTranscriptionState> {
  return requestState(port, '/settings', { method: 'PUT', body: JSON.stringify(patch) });
}

export function saveCloudKey(port: number, provider: CloudProviderId, apiKey: string): Promise<CloudTranscriptionState> {
  return requestState(port, `/keys/${provider}`, { method: 'PUT', body: JSON.stringify({ api_key: apiKey }) });
}

export function deleteCloudKey(port: number, provider: CloudProviderId): Promise<CloudTranscriptionState> {
  return requestState(port, `/keys/${provider}`, { method: 'DELETE' });
}

export async function checkCloudProvider(port: number, provider: CloudProviderId): Promise<CloudCheckResult> {
  const result = parseCloudCheckResult(await request(port, '/check', { method: 'POST', body: JSON.stringify({ provider }) }));
  if (result === null) throw new Error('The connection check response was not understood.');
  return result;
}
