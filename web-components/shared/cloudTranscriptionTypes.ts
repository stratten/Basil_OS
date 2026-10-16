export type CloudProviderId = 'deepgram' | 'assemblyai';
export type CloudConnection = 'own_key' | 'basil_account';
export type CloudStatusState = 'off' | 'connecting' | 'streaming' | 'fallback';

export interface CloudProviderInfo {
  id: CloudProviderId;
  label: string;
  has_key: boolean;
}

export interface CloudStatus {
  state: CloudStatusState;
  provider: string | null;
  tier: string | null;
  reason: string | null;
}

export interface CloudTranscriptionState {
  enabled: boolean;
  provider: CloudProviderId;
  connection: CloudConnection;
  acknowledged: boolean;
  account_available: boolean;
  providers: CloudProviderInfo[];
  status: CloudStatus;
}

export interface CloudCheckResult {
  ok: boolean;
  message: string;
}

export interface CloudSettingsPatch {
  enabled?: boolean;
  provider?: CloudProviderId;
  connection?: CloudConnection;
  acknowledge_disclosure?: boolean;
}

export const CLOUD_STATUS_EVENT_TYPE = 'cloud_transcription_status';
export const MIN_API_KEY_LENGTH = 8;

const PROVIDERS: readonly string[] = ['deepgram', 'assemblyai'];
const CONNECTIONS: readonly string[] = ['own_key', 'basil_account'];
const STATES: readonly string[] = ['off', 'connecting', 'streaming', 'fallback'];

function nullableString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** A well-formed status from an untrusted payload (a REST body or a socket frame), or null when it is not usable. */
export function parseCloudStatus(value: unknown): CloudStatus | null {
  if (typeof value !== 'object' || value === null) return null;
  const { state, provider, tier, reason } = value as Record<string, unknown>;
  if (typeof state !== 'string' || !STATES.includes(state)) return null;
  return { state: state as CloudStatusState, provider: nullableString(provider), tier: nullableString(tier), reason: nullableString(reason) };
}

function parseProvider(value: unknown): CloudProviderInfo | null {
  if (typeof value !== 'object' || value === null) return null;
  const { id, label, has_key: hasKey } = value as Record<string, unknown>;
  if (typeof id !== 'string' || !PROVIDERS.includes(id) || typeof label !== 'string' || typeof hasKey !== 'boolean') return null;
  return { id: id as CloudProviderId, label, has_key: hasKey };
}

export function parseCloudTranscriptionState(value: unknown): CloudTranscriptionState | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as Record<string, unknown>;
  const { enabled, provider, connection, acknowledged, account_available: accountAvailable, providers } = record;
  if (typeof enabled !== 'boolean' || typeof acknowledged !== 'boolean' || typeof accountAvailable !== 'boolean') return null;
  if (typeof provider !== 'string' || !PROVIDERS.includes(provider)) return null;
  if (typeof connection !== 'string' || !CONNECTIONS.includes(connection)) return null;
  if (!Array.isArray(providers)) return null;
  const status = parseCloudStatus(record.status);
  if (status === null) return null;
  const parsedProviders = providers.map(parseProvider).filter((item): item is CloudProviderInfo => item !== null);
  if (parsedProviders.length === 0) return null;
  return {
    enabled,
    provider: provider as CloudProviderId,
    connection: connection as CloudConnection,
    acknowledged,
    account_available: accountAvailable,
    providers: parsedProviders,
    status,
  };
}

export function parseCloudCheckResult(value: unknown): CloudCheckResult | null {
  if (typeof value !== 'object' || value === null) return null;
  const { ok, message } = value as Record<string, unknown>;
  return typeof ok === 'boolean' && typeof message === 'string' ? { ok, message } : null;
}
