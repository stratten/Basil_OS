import type { CloudTranscriptionState } from './cloudTranscriptionTypes';

export function cloudState(overrides: Partial<CloudTranscriptionState> = {}): CloudTranscriptionState {
  return {
    enabled: false,
    provider: 'deepgram',
    connection: 'own_key',
    acknowledged: false,
    account_available: false,
    providers: [
      { id: 'deepgram', label: 'Deepgram', has_key: false },
      { id: 'assemblyai', label: 'AssemblyAI', has_key: false },
    ],
    status: { state: 'off', provider: null, tier: null, reason: null },
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}
