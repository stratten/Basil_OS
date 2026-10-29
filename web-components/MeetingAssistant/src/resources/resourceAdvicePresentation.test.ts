import { describe, expect, it } from 'vitest';
import { adviceChipLabel, formatAdviceDuration, mostSevere } from './resourceAdvicePresentation';
import type { ResourceAdvice } from './resourceAdviceTypes';

function advice(id: string, severity: ResourceAdvice['severity'], title = id): ResourceAdvice {
  return { id, severity, title, detail: 'detail', action: 'none', raised_at: 0 };
}

describe('formatAdviceDuration', () => {
  const at = (seconds: number) => seconds * 1000;
  it('says just now under a minute, including a clock that is slightly behind the server', () => {
    expect(formatAdviceDuration(1000, at(1000))).toBe('just now');
    expect(formatAdviceDuration(1000, at(1059))).toBe('just now');
    expect(formatAdviceDuration(1000, at(990))).toBe('just now');
  });
  it('counts minutes and then hours', () => {
    expect(formatAdviceDuration(1000, at(1060))).toBe('for 1 min');
    expect(formatAdviceDuration(1000, at(1000 + 59 * 60 + 59))).toBe('for 59 min');
    expect(formatAdviceDuration(1000, at(1000 + 3600))).toBe('for 1 h');
    expect(formatAdviceDuration(1000, at(1000 + 3600 + 5 * 60))).toBe('for 1 h 5 min');
  });
});

describe('adviceChipLabel and mostSevere', () => {
  it('labels with the first title and counts the rest', () => {
    expect(adviceChipLabel([])).toBe('');
    expect(adviceChipLabel([advice('a', 'info', 'First')])).toBe('First');
    expect(adviceChipLabel([advice('a', 'info', 'First'), advice('b', 'info'), advice('c', 'info')])).toBe('First and 2 more');
  });
  it('reports the highest severity present', () => {
    expect(mostSevere([advice('a', 'info')])).toBe('info');
    expect(mostSevere([advice('a', 'info'), advice('b', 'warning')])).toBe('warning');
    expect(mostSevere([advice('a', 'warning'), advice('b', 'critical')])).toBe('critical');
    expect(mostSevere([])).toBe('info');
  });
});
