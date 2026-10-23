import { describe, expect, it } from 'vitest';
import {
  parseResponseTimeLimit,
  responseCountdownState,
  responseTimeLimitFromContext,
  responseTimeoutSentences,
  secondsUntilDeadline,
} from './responseTimeLimit';

const wire = { deadline_at: '2026-10-04T23:42:00+00:00', limit_seconds: 120, on_timeout: 'deny_and_retry' };

describe('parseResponseTimeLimit', () => {
  it('reads the backend deadline as epoch milliseconds', () => {
    expect(parseResponseTimeLimit(wire)).toEqual({
      deadlineMs: Date.parse('2026-10-04T23:42:00+00:00'),
      limitSeconds: 120,
      onTimeout: 'deny_and_retry',
    });
  });

  it.each([
    ['nothing', undefined],
    ['a string', 'soon'],
    ['an array', []],
    ['no deadline', { limit_seconds: 60, on_timeout: 'deny' }],
    ['an unreadable deadline', { ...wire, deadline_at: 'tomorrow-ish' }],
    ['no length', { deadline_at: wire.deadline_at, on_timeout: 'deny' }],
    ['a zero length', { ...wire, limit_seconds: 0 }],
    ['a text length', { ...wire, limit_seconds: '120' }],
  ])('yields no countdown for %s', (_label, raw) => {
    expect(parseResponseTimeLimit(raw)).toBeUndefined();
  });

  it('keeps an unnamed outcome so the wording can stay generic', () => {
    expect(parseResponseTimeLimit({ ...wire, on_timeout: undefined })?.onTimeout).toBe('');
  });
});

describe('responseTimeLimitFromContext', () => {
  it('spreads the countdown only when the context carries a valid one', () => {
    expect(responseTimeLimitFromContext({ cwd: '/tmp', time_limit: wire }).time_limit?.limitSeconds).toBe(120);
    expect(responseTimeLimitFromContext({ cwd: '/tmp' })).toEqual({});
    expect(responseTimeLimitFromContext(null)).toEqual({});
    expect(responseTimeLimitFromContext({ time_limit: { limit_seconds: 5 } })).toEqual({});
  });
});

describe('secondsUntilDeadline', () => {
  it('rounds up so zero means the time is truly up', () => {
    expect(secondsUntilDeadline(10_000, 8_500)).toBe(2);
    expect(secondsUntilDeadline(10_000, 9_999)).toBe(1);
    expect(secondsUntilDeadline(10_000, 10_000)).toBe(0);
    expect(secondsUntilDeadline(10_000, 12_000)).toBe(0);
  });
});

describe('responseCountdownState', () => {
  it('turns urgent in the last ten seconds and expires at zero', () => {
    expect(responseCountdownState(120, 300)).toBe('running');
    expect(responseCountdownState(11, 300)).toBe('running');
    expect(responseCountdownState(10, 300)).toBe('urgent');
    expect(responseCountdownState(1, 300)).toBe('urgent');
    expect(responseCountdownState(0, 300)).toBe('expired');
  });

  it('uses the last quarter for a wait shorter than forty seconds', () => {
    expect(responseCountdownState(20, 30)).toBe('running');
    expect(responseCountdownState(7, 30)).toBe('urgent');
  });
});

describe('responseTimeoutSentences', () => {
  it('says what Basil does for each outcome, before and after the deadline', () => {
    expect(responseTimeoutSentences('deny').pending).toContain('treat this as declined');
    expect(responseTimeoutSentences('deny_and_retry').pending).toContain('try another approach');
    expect(responseTimeoutSentences('stop_and_ask').pending).toContain('stop the command');
    expect(responseTimeoutSentences('stop_and_ask').expired).toContain('stopping the command');
    expect(responseTimeoutSentences('continue_without').pending).toContain('carry on without it');
    expect(responseTimeoutSentences('something_new')).toEqual({
      pending: "If you don't respond, Basil will move on.",
      expired: 'Time limit reached. Basil is moving on.',
    });
  });
});
