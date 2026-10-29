import { companionBaseUrl, companionSocketUrl } from '../companion/companionApi';
import { parseResourceAdviceState, type ResourceAdviceState, type ThermalState } from './resourceAdviceTypes';

export const resourceAdviceSocketUrl = companionSocketUrl;

async function requestState(port: number, path: string, init: RequestInit = {}): Promise<ResourceAdviceState> {
  const response = await fetch(`${companionBaseUrl(port)}/meetings/resource-advice${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error(`The resource advice request failed (${response.status}).`);
  const state = parseResourceAdviceState(await response.json());
  if (state === null) throw new Error('The resource advice response was not understood.');
  return state;
}

export function fetchResourceAdvice(port: number): Promise<ResourceAdviceState> {
  return requestState(port, '');
}

export function reportThermalState(port: number, thermalState: ThermalState): Promise<ResourceAdviceState> {
  return requestState(port, '/client-state', { method: 'PUT', body: JSON.stringify({ thermal_state: thermalState }) });
}

export function dismissResourceAdvice(port: number, adviceId: string): Promise<ResourceAdviceState> {
  return requestState(port, `/${encodeURIComponent(adviceId)}/dismiss`, { method: 'POST', body: '{}' });
}
