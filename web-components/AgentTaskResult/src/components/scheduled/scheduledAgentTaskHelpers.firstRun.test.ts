import { describe, expect, it } from 'vitest';
import { composeFirstRun, firstRunFromNextRun, resolveFirstRunDate, splitFirstRun } from './scheduledAgentTaskHelpers';

// 2026-10-27 17:26:14 UTC is 13:26 in New York (EDT) and 22:56 in Kolkata (IST).
const NOW = new Date('2026-10-27T17:26:14Z');

describe('resolveFirstRunDate', () => {
  it('uses today while the time is still ahead in the schedule timezone', () => {
    expect(resolveFirstRunDate('13:27', 'America/New_York', NOW)).toBe('2026-10-27');
  });

  it('uses tomorrow once the time has passed or is right now', () => {
    expect(resolveFirstRunDate('13:26', 'America/New_York', NOW)).toBe('2026-10-28');
    expect(resolveFirstRunDate('09:00', 'America/New_York', NOW)).toBe('2026-10-28');
  });

  it('reads "now" in the schedule timezone, not the machine timezone', () => {
    // It is already 22:56 in Kolkata, so 23:00 is still today but 22:00 is tomorrow.
    expect(resolveFirstRunDate('23:00', 'Asia/Kolkata', NOW)).toBe('2026-10-27');
    expect(resolveFirstRunDate('22:00', 'Asia/Kolkata', NOW)).toBe('2026-10-28');
  });

  it('rolls over month and year ends', () => {
    expect(resolveFirstRunDate('01:00', 'UTC', new Date('2026-12-31T12:00:00Z'))).toBe('2027-01-01');
    expect(resolveFirstRunDate('01:00', 'UTC', new Date('2026-02-28T12:00:00Z'))).toBe('2026-03-01');
  });

  it('survives an unknown timezone name', () => {
    expect(resolveFirstRunDate('13:27', 'Not/AZone', NOW)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('composeFirstRun', () => {
  it('is empty without a time', () => {
    expect(composeFirstRun({ date: '', time: '' }, 'UTC', NOW)).toBe('');
    expect(composeFirstRun({ date: '2030-01-01', time: '' }, 'UTC', NOW)).toBe('');
  });

  it('keeps an explicit date and infers a missing one', () => {
    expect(composeFirstRun({ date: '2030-01-01', time: '09:30' }, 'UTC', NOW)).toBe('2030-01-01T09:30');
    expect(composeFirstRun({ date: '', time: '13:27' }, 'America/New_York', NOW)).toBe('2026-10-27T13:27');
  });
});

describe('splitFirstRun', () => {
  it('splits a stored first run and ignores anything malformed', () => {
    expect(splitFirstRun('2030-01-01T09:30')).toEqual({ date: '2030-01-01', time: '09:30' });
    expect(splitFirstRun('2030-01-01T09:30:00+00:00')).toEqual({ date: '2030-01-01', time: '09:30' });
    expect(splitFirstRun('garbage')).toEqual({ date: '', time: '' });
    expect(splitFirstRun('')).toEqual({ date: '', time: '' });
  });
});

describe('firstRunFromNextRun', () => {
  it('shows an upcoming run as wall-clock time in the schedule timezone', () => {
    expect(firstRunFromNextRun('2026-10-27T17:41:14+00:00', 'America/New_York', NOW)).toEqual({ date: '2026-10-27', time: '13:41' });
    expect(firstRunFromNextRun('2026-10-27T17:41:14+00:00', 'Asia/Kolkata', NOW)).toEqual({ date: '2026-10-27', time: '23:11' });
  });

  it('is empty when there is no run ahead, or the value is unusable', () => {
    expect(firstRunFromNextRun(null, 'UTC', NOW)).toEqual({ date: '', time: '' });
    expect(firstRunFromNextRun(undefined, 'UTC', NOW)).toEqual({ date: '', time: '' });
    expect(firstRunFromNextRun('2020-01-01T00:00:00Z', 'UTC', NOW)).toEqual({ date: '', time: '' });
    expect(firstRunFromNextRun('garbage', 'UTC', NOW)).toEqual({ date: '', time: '' });
  });

  it('round-trips with composeFirstRun, so saving an untouched form keeps the run', () => {
    const fields = firstRunFromNextRun('2026-10-27T17:41:14+00:00', 'America/New_York', NOW);
    expect(composeFirstRun(fields, 'America/New_York', NOW)).toBe('2026-10-27T13:41');
  });
});
