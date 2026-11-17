import { describe, expect, it } from 'vitest';
import { describeFollowUpDue } from './followUpTime';

const NOW = new Date(2026, 9, 12, 10, 0, 0);

describe('describeFollowUpDue', () => {
  it('uses only the time of day for a check later today', () => {
    const due = new Date(2026, 9, 12, 15, 15, 0);
    const description = describeFollowUpDue(due.toISOString(), NOW);
    expect(description?.isDue).toBe(false);
    expect(description?.rowText).toBe(`Checks again ${due.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`);
    expect(description?.sentence).toContain('Basil will check again automatically at');
  });

  it('includes the date for a check on another day', () => {
    const due = new Date(2026, 9, 14, 9, 30, 0);
    const description = describeFollowUpDue(due.toISOString(), NOW);
    expect(description?.rowText).toContain(due.toLocaleDateString([], { month: 'short', day: 'numeric' }));
  });

  it('reports an overdue check as imminent', () => {
    const description = describeFollowUpDue(new Date(2026, 9, 12, 9, 59, 0).toISOString(), NOW);
    expect(description).toMatchObject({ isDue: true, rowText: 'Checking again soon', sentence: 'Basil is about to check again.' });
  });

  it('returns null for an unparseable time', () => {
    expect(describeFollowUpDue('not a date', NOW)).toBeNull();
    expect(describeFollowUpDue('', NOW)).toBeNull();
  });
});
