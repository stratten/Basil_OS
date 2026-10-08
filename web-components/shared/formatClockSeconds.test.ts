import { describe, expect, it } from 'vitest';
import { formatClockSeconds } from './formatClockSeconds';

describe('formatClockSeconds', () => {
  it('formats sub-minute values with a leading zero on the seconds', () => {
    expect(formatClockSeconds(0)).toBe('0:00');
    expect(formatClockSeconds(7)).toBe('0:07');
    expect(formatClockSeconds(59)).toBe('0:59');
  });

  it('formats minutes and seconds without padding the minutes', () => {
    expect(formatClockSeconds(60)).toBe('1:00');
    expect(formatClockSeconds(125)).toBe('2:05');
    expect(formatClockSeconds(3599)).toBe('59:59');
  });

  it('switches to h:mm:ss at one hour and keeps counting hours', () => {
    expect(formatClockSeconds(3600)).toBe('1:00:00');
    expect(formatClockSeconds(3725)).toBe('1:02:05');
    expect(formatClockSeconds(36000 + 61)).toBe('10:01:01');
  });

  it('pads the minutes when requested, and never changes the hour form', () => {
    expect(formatClockSeconds(123, { padMinutes: true })).toBe('02:03');
    expect(formatClockSeconds(0, { padMinutes: true })).toBe('00:00');
    expect(formatClockSeconds(754, { padMinutes: true })).toBe('12:34');
    expect(formatClockSeconds(3725, { padMinutes: true })).toBe('1:02:05');
  });

  it('floors fractional seconds', () => {
    expect(formatClockSeconds(12.9)).toBe('0:12');
    expect(formatClockSeconds(59.999)).toBe('0:59');
  });

  it('treats negative, NaN, and infinite input as zero', () => {
    expect(formatClockSeconds(-4)).toBe('0:00');
    expect(formatClockSeconds(Number.NaN)).toBe('0:00');
    expect(formatClockSeconds(Number.POSITIVE_INFINITY)).toBe('0:00');
    expect(formatClockSeconds(Number.NEGATIVE_INFINITY, { padMinutes: true })).toBe('00:00');
  });
});
