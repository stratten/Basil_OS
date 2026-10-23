import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  formatTodoDateOnly,
  isTodoDueDateOverdue,
  localTodayDateOnly,
  parseTodoDateOnlyAsLocalDate,
  todoDateOnly,
} from './todoDates';

describe('todoDateOnly', () => {
  it('extracts the YYYY-MM-DD substring from a UTC-midnight instant string', () => {
    expect(todoDateOnly('2026-09-13T00:00:00.000Z')).toBe('2026-09-13');
  });
});

describe('parseTodoDateOnlyAsLocalDate', () => {
  it('builds a local Date from the Y/M/D components without a UTC round-trip', () => {
    const parsed = parseTodoDateOnlyAsLocalDate('2026-09-13T00:00:00.000Z');
    expect(parsed.getFullYear()).toBe(2026);
    expect(parsed.getMonth()).toBe(8);
    expect(parsed.getDate()).toBe(13);
  });
});

describe('formatTodoDateOnly and isTodoDueDateOverdue', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('never flags a due date of today as overdue, in any timezone offset', () => {
    vi.setSystemTime(new Date('2026-09-13T23:30:00.000Z'));
    expect(isTodoDueDateOverdue('2026-09-13T00:00:00.000Z')).toBe(false);
  });

  it('flags a due date of yesterday as overdue', () => {
    vi.setSystemTime(new Date('2026-09-13T12:00:00.000Z'));
    expect(isTodoDueDateOverdue('2026-09-12T00:00:00.000Z')).toBe(true);
  });

  it('does not flag a due date of today as overdue right after local midnight in a negative-offset zone', () => {
    // Simulates the exact failure mode from the bug report: the stored value
    // is UTC midnight of "today", but the current instant is already past
    // that UTC midnight while it is still "today" in a negative-offset
    // timezone (e.g. US Eastern, UTC-4). A naive instant comparison
    // (`new Date(due_at) < new Date()`) would incorrectly flag this overdue.
    vi.setSystemTime(new Date('2026-09-13T04:00:00.000Z'));
    expect(isTodoDueDateOverdue('2026-09-13T00:00:00.000Z')).toBe(false);
  });

  it('formats a date-only value consistently regardless of a UTC round-trip', () => {
    expect(formatTodoDateOnly('2026-09-13T00:00:00.000Z')).toBe(
      parseTodoDateOnlyAsLocalDate('2026-09-13T00:00:00.000Z').toLocaleDateString(),
    );
  });

  it('computes local "today" using the local calendar day, not the UTC day', () => {
    vi.setSystemTime(new Date('2026-09-13T12:00:00.000Z'));
    const today = new Date();
    const expected = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    expect(localTodayDateOnly()).toBe(expected);
  });
});
