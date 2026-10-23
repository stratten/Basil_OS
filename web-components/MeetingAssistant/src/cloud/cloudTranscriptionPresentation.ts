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

export const LIVE_LOCAL_VALUE = 'local';
export const LIVE_BASIL_ACCOUNT_VALUE = 'basil_account';

export interface LiveModelOption {
  value: string;
  label: string;
  category: 'local' | 'api';
}

/** The engines live transcription can run on: the local model, plus each cloud service the user has already opted into and set up in Settings. Cloud choices stay hidden until the disclosure was acknowledged. */
export function liveModelOptions(state: CloudTranscriptionState | null, localLabel: string): LiveModelOption[] {
  const options: LiveModelOption[] = [{ value: LIVE_LOCAL_VALUE, label: localLabel, category: 'local' }];
  if (state === null || !state.acknowledged) return options;
  for (const provider of state.providers) {
    if (provider.has_key) options.push({ value: provider.id, label: provider.label, category: 'api' });
  }
  if (state.account_available) options.push({ value: LIVE_BASIL_ACCOUNT_VALUE, label: 'Basil account', category: 'api' });
  return options;
}

/** The option the saved settings select by default. Anything that is not an available cloud choice reads as local. */
export function liveDefaultValue(state: CloudTranscriptionState | null, options: readonly LiveModelOption[]): string {
  if (state === null || !state.enabled) return LIVE_LOCAL_VALUE;
  const value = state.connection === 'basil_account' ? LIVE_BASIL_ACCOUNT_VALUE : state.provider;
  return options.some((option) => option.value === value) ? value : LIVE_LOCAL_VALUE;
}

/** The option shown for the next recording: this recording's choice when it is still available, otherwise the saved default. */
export function liveModelValue(state: CloudTranscriptionState | null, options: readonly LiveModelOption[], override?: string | null): string {
  if (override != null && options.some((option) => option.value === override)) return override;
  return liveDefaultValue(state, options);
}

/** What to send for a pick: null when it equals the saved default (no deviation), otherwise the engine for this one recording. */
export function liveEngineChoice(value: string, state: CloudTranscriptionState | null, options: readonly LiveModelOption[]): string | null {
  return value === liveDefaultValue(state, options) ? null : value;
}

/** The only on-device model live transcription runs on a Mac. The live engine maps every Whisper choice to its CTranslate2 'base' size when there is no CUDA GPU (config_mapper.py), so the selected transcription model does not change it. */
export const LOCAL_LIVE_MODEL_LABEL = 'Whisper Base';
