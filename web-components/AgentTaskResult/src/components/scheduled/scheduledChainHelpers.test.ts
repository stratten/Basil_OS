import { describe, expect, it } from 'vitest';
import type { ScheduledChainConfig } from '../../types';
import {
  DEFAULT_CHAIN_FORM,
  chainConfigChanged,
  chainConfigFromForm,
  chainFormError,
  chainFormFromConfig,
  cleanExclusionWindows,
  describeChain,
  describeExclusionWindows,
  describeMinutes,
  effectiveChainConfig,
  exclusionWindowsError,
  exclusionWindowsFromConfig,
  toggleWindowDay,
  withExclusionWindows,
} from './scheduledChainHelpers';

const chained = { ...DEFAULT_CHAIN_FORM, chained: true };

describe('chain form and payload', () => {
  it('sends independent runs by default', () => {
    expect(chainConfigFromForm(DEFAULT_CHAIN_FORM)).toEqual({ mode: 'independent' });
    expect(chainFormError(DEFAULT_CHAIN_FORM)).toBeNull();
  });

  it('starts a chained schedule with both limits and carry-over on', () => {
    expect(chainConfigFromForm(chained)).toEqual({ mode: 'chained', carry_over: true, max_runs: 24, max_age_minutes: 1440 });
  });

  it('converts the time limit to minutes in every unit', () => {
    expect(chainConfigFromForm({ ...chained, limitRuns: false, ageValue: '6', ageUnit: 'hours' })).toEqual({ mode: 'chained', carry_over: true, max_age_minutes: 360 });
    expect(chainConfigFromForm({ ...chained, limitRuns: false, ageValue: '7', ageUnit: 'days' }).max_age_minutes).toBe(10080);
    expect(chainConfigFromForm({ ...chained, limitRuns: false, ageValue: '90', ageUnit: 'minutes' }).max_age_minutes).toBe(90);
  });

  it('omits an unticked limit and keeps carry-over off when asked', () => {
    expect(chainConfigFromForm({ ...chained, limitAge: false, carryOver: false })).toEqual({ mode: 'chained', carry_over: false, max_runs: 24 });
  });

  it('rejects a chained schedule with no limit, and malformed limits', () => {
    expect(chainFormError({ ...chained, limitRuns: false, limitAge: false })).toMatch(/run limit, a time limit, or both/);
    expect(chainFormError({ ...chained, maxRuns: '0' })).toMatch(/whole number from 1 to 1,000/);
    expect(chainFormError({ ...chained, maxRuns: '2.5' })).toMatch(/whole number/);
    expect(chainFormError({ ...chained, maxRuns: '1001' })).toMatch(/whole number/);
    expect(chainFormError({ ...chained, maxRuns: '' })).toMatch(/whole number/);
    expect(chainFormError({ ...chained, ageValue: '-3' })).toMatch(/time limit/);
    expect(chainFormError({ ...chained, ageValue: '367', ageUnit: 'days' })).toMatch(/up to 366 days/);
  });

  it('does not validate limits that are switched off', () => {
    expect(chainFormError({ ...chained, limitAge: false, ageValue: 'junk' })).toBeNull();
    expect(chainFormError({ ...chained, limitRuns: false, maxRuns: 'junk' })).toBeNull();
  });

  it('round-trips a saved config through the form', () => {
    const saved: ScheduledChainConfig = { mode: 'chained', carry_over: false, max_runs: 4, max_age_minutes: 90 };
    const form = chainFormFromConfig(saved);
    expect(form).toMatchObject({ chained: true, carryOver: false, limitRuns: true, maxRuns: '4', limitAge: true, ageValue: '90', ageUnit: 'minutes' });
    expect(chainConfigFromForm(form)).toEqual(saved);
    expect(chainFormFromConfig({ mode: 'chained', max_age_minutes: 2880 })).toMatchObject({ ageValue: '2', ageUnit: 'days', limitRuns: false });
    expect(chainFormFromConfig({ mode: 'chained', max_age_minutes: 120 })).toMatchObject({ ageValue: '2', ageUnit: 'hours' });
  });

  it('treats missing or independent saved configs as the default form', () => {
    expect(chainFormFromConfig(undefined)).toEqual(DEFAULT_CHAIN_FORM);
    expect(chainFormFromConfig(null)).toEqual(DEFAULT_CHAIN_FORM);
    expect(chainFormFromConfig({ mode: 'independent' })).toEqual(DEFAULT_CHAIN_FORM);
  });

  it('never sends a chain for a one-time schedule', () => {
    expect(effectiveChainConfig(chained, 'one_time')).toEqual({ mode: 'independent' });
    expect(effectiveChainConfig(chained, 'recurring').mode).toBe('chained');
  });

  it('reports a change only when the effective settings differ from what is saved', () => {
    const saved: ScheduledChainConfig = { mode: 'chained', carry_over: true, max_runs: 24, max_age_minutes: 1440 };
    expect(chainConfigChanged(chained, saved, 'recurring')).toBe(false);
    expect(chainConfigChanged({ ...chained, carryOver: false }, saved, 'recurring')).toBe(true);
    expect(chainConfigChanged(DEFAULT_CHAIN_FORM, undefined, 'recurring')).toBe(false);
    expect(chainConfigChanged(chained, saved, 'one_time')).toBe(true);
    expect(chainConfigChanged(DEFAULT_CHAIN_FORM, saved, 'recurring')).toBe(true);
  });

  it('describes a chain in plain words', () => {
    expect(describeChain(undefined)).toBe('Each run is its own task');
    expect(describeChain({ mode: 'chained', carry_over: true, max_runs: 8, max_age_minutes: 360 })).toBe(
      'Continues one conversation, starting a new one after 8 runs or 6 hours, carrying the last result over',
    );
    expect(describeChain({ mode: 'chained', carry_over: false, max_runs: 1 })).toBe(
      'Continues one conversation, starting a new one after 1 run, starting blank',
    );
  });

  it('describes minutes in the largest whole unit', () => {
    expect([30, 60, 90, 360, 1440, 10080].map(describeMinutes)).toEqual(['30 minutes', '1 hour', '90 minutes', '6 hours', '1 day', '7 days']);
  });
});

describe('quiet-hours windows', () => {
  it('reads windows from a stored config and ignores junk', () => {
    expect(exclusionWindowsFromConfig({ exclusion_windows: [{ start: '22:00', end: '07:00' }, { start: '12:00', end: '13:00', days: [6, 5, 5, 9, 'x'] }, 'junk', { start: 5 }] })).toEqual([
      { start: '22:00', end: '07:00', days: [] },
      { start: '12:00', end: '13:00', days: [5, 6] },
    ]);
    expect(exclusionWindowsFromConfig({})).toEqual([]);
    expect(exclusionWindowsFromConfig(null)).toEqual([]);
    expect(exclusionWindowsFromConfig({ exclusion_windows: 'nope' })).toEqual([]);
  });

  it('omits weekdays from the payload when a window applies every day', () => {
    expect(cleanExclusionWindows([{ start: '22:00', end: '07:00', days: [] }, { start: '08:00', end: '09:00', days: [3, 1, 3] }])).toEqual([
      { start: '22:00', end: '07:00' },
      { start: '08:00', end: '09:00', days: [1, 3] },
    ]);
  });

  it('adds windows to a schedule config only when there are some, leaving the stored shape unchanged otherwise', () => {
    const base = { mode: 'interval', minutes: 30 };
    expect(withExclusionWindows(base, [])).toBe(base);
    expect(withExclusionWindows(base, [{ start: '22:00', end: '07:00', days: [] }])).toEqual({
      mode: 'interval',
      minutes: 30,
      exclusion_windows: [{ start: '22:00', end: '07:00' }],
    });
  });

  it('toggles a weekday on and off, keeping the list sorted', () => {
    const window = { start: '22:00', end: '07:00', days: [4] };
    expect(toggleWindowDay(window, 1).days).toEqual([1, 4]);
    expect(toggleWindowDay(window, 4).days).toEqual([]);
    expect(toggleWindowDay({ start: '22:00', end: '07:00' }, 2).days).toEqual([2]);
  });

  it('validates windows', () => {
    expect(exclusionWindowsError([{ start: '22:00', end: '07:00', days: [] }])).toBeNull();
    expect(exclusionWindowsError([{ start: '', end: '07:00', days: [] }])).toMatch(/start time and an end time/);
    expect(exclusionWindowsError([{ start: '22:00', end: '25:00', days: [] }])).toMatch(/start time and an end time/);
    expect(exclusionWindowsError([{ start: '00:00', end: '00:00', days: [] }])).toMatch(/choose the weekdays/);
    expect(exclusionWindowsError([{ start: '00:00', end: '00:00', days: [5, 6] }])).toBeNull();
    expect(exclusionWindowsError(Array.from({ length: 9 }, () => ({ start: '01:00', end: '02:00', days: [] })))).toMatch(/at most 8/);
  });

  it('describes windows in 12-hour time with weekdays', () => {
    expect(
      describeExclusionWindows([
        { start: '22:00', end: '07:00', days: [] },
        { start: '00:00', end: '00:00', days: [5, 6] },
        { start: '12:00', end: '13:30', days: [0, 1] },
      ]),
    ).toBe('10:00 PM to 7:00 AM; Sat, Sun, all day; 12:00 PM to 1:30 PM on Mon, Tue');
  });
});
