export type ResourceAdviceSeverity = 'info' | 'warning' | 'critical';
export type ResourceAdviceAction = 'open_settings' | 'none';
export type ThermalState = 'nominal' | 'fair' | 'serious' | 'critical';

export interface ResourceAdvice {
  id: string;
  severity: ResourceAdviceSeverity;
  title: string;
  detail: string;
  action: ResourceAdviceAction;
  /** Wall-clock epoch seconds when the condition was first confirmed. */
  raised_at: number;
}

export interface ResourceAdviceState {
  revision: number;
  advice: ResourceAdvice[];
}

export const EMPTY_RESOURCE_ADVICE: ResourceAdviceState = { revision: 0, advice: [] };

export const THERMAL_REPORT_INTERVAL_MS = 60_000;

const SEVERITIES: readonly string[] = ['info', 'warning', 'critical'];
const ACTIONS: readonly string[] = ['open_settings', 'none'];
const THERMAL_STATES: readonly string[] = ['nominal', 'fair', 'serious', 'critical'];

export function parseThermalState(value: unknown): ThermalState | null {
  return typeof value === 'string' && THERMAL_STATES.includes(value) ? (value as ThermalState) : null;
}

function parseAdvice(value: unknown): ResourceAdvice | null {
  if (typeof value !== 'object' || value === null) return null;
  const candidate = value as Record<string, unknown>;
  const { id, severity, title, detail, action, raised_at: raisedAt } = candidate;
  if (typeof id !== 'string' || id === '' || typeof title !== 'string' || typeof detail !== 'string') return null;
  if (typeof severity !== 'string' || !SEVERITIES.includes(severity)) return null;
  if (typeof action !== 'string' || !ACTIONS.includes(action)) return null;
  if (typeof raisedAt !== 'number' || !Number.isFinite(raisedAt)) return null;
  return { id, severity: severity as ResourceAdviceSeverity, title, detail, action: action as ResourceAdviceAction, raised_at: raisedAt };
}

/** A well-formed state from an untrusted payload, or null when the payload is not usable. Malformed items are dropped. */
export function parseResourceAdviceState(value: unknown): ResourceAdviceState | null {
  if (typeof value !== 'object' || value === null) return null;
  const { revision, advice } = value as Record<string, unknown>;
  if (typeof revision !== 'number' || !Number.isInteger(revision) || revision < 0 || !Array.isArray(advice)) return null;
  const parsed = advice.map(parseAdvice).filter((item): item is ResourceAdvice => item !== null);
  return { revision, advice: parsed };
}
