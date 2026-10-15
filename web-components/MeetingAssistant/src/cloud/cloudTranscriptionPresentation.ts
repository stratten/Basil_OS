import type { CloudStatus, CloudTranscriptionState } from './cloudTranscriptionTypes';

export type CloudChipTone = 'off' | 'on' | 'connecting' | 'streaming' | 'fallback';

const PROVIDER_LABELS: Record<string, string> = {
  deepgram: 'Deepgram',
  assemblyai: 'AssemblyAI',
  basil_account: 'Basil account',
};

export function providerLabel(provider: string | null): string {
  if (provider === null) return 'cloud';
  return PROVIDER_LABELS[provider] ?? 'cloud';
}

export function chipTone(state: CloudTranscriptionState | null): CloudChipTone {
  if (state === null) return 'off';
  if (state.status.state !== 'off') return state.status.state;
  return state.enabled ? 'on' : 'off';
}

export function chipLabel(state: CloudTranscriptionState | null): string {
  if (state === null) return 'Cloud transcription';
  const status: CloudStatus = state.status;
  if (status.state === 'streaming') return `Cloud transcription: ${providerLabel(status.provider)}`;
  if (status.state === 'connecting') return 'Cloud transcription: connecting';
  if (status.state === 'fallback') return 'Cloud transcription failed, using local';
  return state.enabled ? 'Cloud transcription: on' : 'Cloud transcription: off';
}

/** A sentence that tells the user why the local model took over, or null when nothing failed. */
export function fallbackNotice(status: CloudStatus): string | null {
  if (status.state !== 'fallback') return null;
  const reason = status.reason?.trim() ?? '';
  return reason === '' ? 'Cloud transcription stopped. The local model is transcribing instead.' : `${reason} The local model is transcribing instead.`;
}
