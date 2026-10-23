import { describe, expect, it } from 'vitest';
import { formatConversationTimestamp, parseConversationTimestamp } from './chatsPresentation';

describe('parseConversationTimestamp', () => {
  it('treats SQLite space-separated text as UTC', () => {
    expect(parseConversationTimestamp('2026-09-30 12:27:00').toISOString()).toBe('2026-09-30T12:27:00.000Z');
  });

  it('treats offset-less ISO text as UTC, including fractional seconds and minute precision', () => {
    expect(parseConversationTimestamp('2026-09-30T12:27:00.250000').toISOString()).toBe('2026-09-30T12:27:00.250Z');
    expect(parseConversationTimestamp('2026-09-30T12:27').toISOString()).toBe('2026-09-30T12:27:00.000Z');
  });

  it('keeps explicit offsets', () => {
    expect(parseConversationTimestamp('2026-09-30T12:27:00Z').toISOString()).toBe('2026-09-30T12:27:00.000Z');
    expect(parseConversationTimestamp('2026-09-30T08:27:00-04:00').toISOString()).toBe('2026-09-30T12:27:00.000Z');
  });

  it('returns an invalid date for malformed text', () => {
    expect(Number.isNaN(parseConversationTimestamp('not a date').getTime())).toBe(true);
  });
});

describe('formatConversationTimestamp', () => {
  it('formats naive UTC and explicit UTC identically, so the sidebar matches the transcript', () => {
    expect(formatConversationTimestamp('2026-09-30 12:27:00')).toBe(formatConversationTimestamp('2026-09-30T12:27:00Z'));
    expect(formatConversationTimestamp('2026-09-30T12:27:00')).toBe(formatConversationTimestamp('2026-09-30T12:27:00Z'));
  });

  it('returns malformed and empty values unchanged', () => {
    expect(formatConversationTimestamp('not a date')).toBe('not a date');
    expect(formatConversationTimestamp('')).toBe('');
  });
});
