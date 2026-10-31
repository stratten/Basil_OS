import type { ExclusionWindow, ScheduledChainConfig } from '../../types';
import { WEEKDAY_LABELS, formatTime12h } from './scheduledAgentTaskHelpers';

export const MAX_EXCLUSION_WINDOWS = 8;
export const MAX_CHAIN_RUNS = 1000;
export const MAX_CHAIN_AGE_MINUTES = 60 * 24 * 366;

export type ChainAgeUnit = 'minutes' | 'hours' | 'days';

const MINUTES_PER_UNIT: Record<ChainAgeUnit, number> = { minutes: 1, hours: 60, days: 1440 };

export interface ChainFormState {
  chained: boolean;
  limitRuns: boolean;
  maxRuns: string;
  limitAge: boolean;
  ageValue: string;
  ageUnit: ChainAgeUnit;
  carryOver: boolean;
}

// A chained schedule needs at least one limit, so turning chaining on starts with both: a new conversation after 24 runs or one day, whichever comes first.
export const DEFAULT_CHAIN_FORM: ChainFormState = {
  chained: false,
  limitRuns: true,
  maxRuns: '24',
  limitAge: true,
  ageValue: '1',
  ageUnit: 'days',
  carryOver: true,
};

const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;

function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : null;
}

export function describeMinutes(minutes: number): string {
  if (minutes % 1440 === 0) {
    const days = minutes / 1440;
    return `${days} ${days === 1 ? 'day' : 'days'}`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
  }
  return `${minutes} minutes`;
}

export function chainFormFromConfig(config: ScheduledChainConfig | null | undefined): ChainFormState {
  if (!config || config.mode !== 'chained') return { ...DEFAULT_CHAIN_FORM };
  const form: ChainFormState = {
    ...DEFAULT_CHAIN_FORM,
    chained: true,
    carryOver: config.carry_over !== false,
    limitRuns: false,
    limitAge: false,
  };
  if (typeof config.max_runs === 'number' && config.max_runs > 0) {
    form.limitRuns = true;
    form.maxRuns = String(config.max_runs);
  }
  if (typeof config.max_age_minutes === 'number' && config.max_age_minutes > 0) {
    const minutes = config.max_age_minutes;
    form.limitAge = true;
    if (minutes % 1440 === 0) {
      form.ageUnit = 'days';
      form.ageValue = String(minutes / 1440);
    } else if (minutes % 60 === 0) {
      form.ageUnit = 'hours';
      form.ageValue = String(minutes / 60);
    } else {
      form.ageUnit = 'minutes';
      form.ageValue = String(minutes);
    }
  }
  return form;
}

function ageMinutes(form: ChainFormState): number | null {
  const value = wholeNumber(form.ageValue);
  return value === null ? null : value * MINUTES_PER_UNIT[form.ageUnit];
}

// The message to show next to the chain row, or null when the settings can be saved.
export function chainFormError(form: ChainFormState): string | null {
  if (!form.chained) return null;
  if (!form.limitRuns && !form.limitAge) return 'Choose a run limit, a time limit, or both, so one conversation cannot grow without end.';
  if (form.limitRuns) {
    const runs = wholeNumber(form.maxRuns);
    if (runs === null || runs < 1 || runs > MAX_CHAIN_RUNS) return `The run limit must be a whole number from 1 to ${MAX_CHAIN_RUNS.toLocaleString('en-US')}.`;
  }
  if (form.limitAge) {
    const minutes = ageMinutes(form);
    if (minutes === null || minutes < 1 || minutes > MAX_CHAIN_AGE_MINUTES) return 'The time limit must be a whole number, up to 366 days.';
  }
  return null;
}

// What the form means as the payload for the backend. Only call this when `chainFormError` is null.
export function chainConfigFromForm(form: ChainFormState): ScheduledChainConfig {
  if (!form.chained) return { mode: 'independent' };
  const config: ScheduledChainConfig = { mode: 'chained', carry_over: form.carryOver };
  if (form.limitRuns) config.max_runs = Number(form.maxRuns.trim());
  if (form.limitAge) config.max_age_minutes = ageMinutes(form) ?? undefined;
  return config;
}

// The payload to send for the chain on this schedule type: only a recurring schedule can be chained.
export function effectiveChainConfig(form: ChainFormState, scheduleType: 'one_time' | 'recurring'): ScheduledChainConfig {
  return scheduleType === 'recurring' ? chainConfigFromForm(form) : { mode: 'independent' };
}

// Whether the edited chain settings differ from what is saved, so an unrelated edit never resends them.
export function chainConfigChanged(
  form: ChainFormState,
  saved: ScheduledChainConfig | null | undefined,
  scheduleType: 'one_time' | 'recurring',
): boolean {
  const savedNormalized = chainConfigFromForm(chainFormFromConfig(saved));
  return JSON.stringify(effectiveChainConfig(form, scheduleType)) !== JSON.stringify(savedNormalized);
}

export function describeChain(config: ScheduledChainConfig | null | undefined): string {
  if (!config || config.mode !== 'chained') return 'Each run is its own task';
  const limits: string[] = [];
  if (config.max_runs) limits.push(`${config.max_runs} ${config.max_runs === 1 ? 'run' : 'runs'}`);
  if (config.max_age_minutes) limits.push(describeMinutes(config.max_age_minutes));
  const lead = limits.length > 0 ? `Continues one conversation, starting a new one after ${limits.join(' or ')}` : 'Continues one conversation';
  return `${lead}${config.carry_over === false ? ', starting blank' : ', carrying the last result over'}`;
}

export function newExclusionWindow(): ExclusionWindow {
  return { start: '22:00', end: '07:00', days: [] };
}

// Windows from a stored schedule config, tolerant of anything unexpected.
export function exclusionWindowsFromConfig(config: unknown): ExclusionWindow[] {
  const raw = (config as { exclusion_windows?: unknown } | null | undefined)?.exclusion_windows;
  if (!Array.isArray(raw)) return [];
  const windows: ExclusionWindow[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const { start, end, days } = entry as { start?: unknown; end?: unknown; days?: unknown };
    if (typeof start !== 'string' || typeof end !== 'string') continue;
    const dayList = Array.isArray(days) ? days.map(Number).filter(day => Number.isInteger(day) && day >= 0 && day <= 6) : [];
    windows.push({ start, end, days: [...new Set(dayList)].sort((a, b) => a - b) });
  }
  return windows;
}

// The canonical payload form: weekdays sorted and unique, and omitted when the window applies every day.
export function cleanExclusionWindows(windows: ExclusionWindow[]): ExclusionWindow[] {
  return windows.map(window => {
    const days = [...new Set(window.days ?? [])].filter(day => Number.isInteger(day) && day >= 0 && day <= 6).sort((a, b) => a - b);
    return days.length > 0 ? { start: window.start, end: window.end, days } : { start: window.start, end: window.end };
  });
}

export function withExclusionWindows(config: Record<string, unknown>, windows: ExclusionWindow[]): Record<string, unknown> {
  const cleaned = cleanExclusionWindows(windows);
  return cleaned.length > 0 ? { ...config, exclusion_windows: cleaned } : config;
}

export function toggleWindowDay(window: ExclusionWindow, day: number): ExclusionWindow {
  const days = window.days ?? [];
  const next = days.includes(day) ? days.filter(value => value !== day) : [...days, day].sort((a, b) => a - b);
  return { ...window, days: next };
}

// The message to show under the quiet-hours rows, or null when they can be saved.
export function exclusionWindowsError(windows: ExclusionWindow[]): string | null {
  if (windows.length > MAX_EXCLUSION_WINDOWS) return `A schedule can have at most ${MAX_EXCLUSION_WINDOWS} quiet-hours windows.`;
  for (const window of windows) {
    if (!CLOCK.test(window.start) || !CLOCK.test(window.end)) return 'Each quiet-hours window needs a start time and an end time.';
    if (window.start === window.end && (window.days ?? []).length === 0) {
      return 'A window whose start and end are the same covers a whole day, so choose the weekdays it applies to.';
    }
  }
  return null;
}

export function describeExclusionWindows(windows: ExclusionWindow[]): string {
  return windows
    .map(window => {
      const days = (window.days ?? []).map(day => WEEKDAY_LABELS[day] ?? String(day)).join(', ');
      if (window.start === window.end) return `${days || 'Every day'}, all day`;
      const span = `${formatTime12h(window.start)} to ${formatTime12h(window.end)}`;
      return days ? `${span} on ${days}` : span;
    })
    .join('; ');
}
