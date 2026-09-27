import { describe, expect, it } from 'vitest';
import { normalizeProgressStepText } from './progressStepText';

describe('normalizeProgressStepText', () => {
  it('normalizes escaped Windows line breaks', () => {
    expect(normalizeProgressStepText('Planning\\r\\nExecuting')).toBe('Planning\nExecuting');
  });

  it('normalizes escaped Unix line breaks', () => {
    expect(normalizeProgressStepText('Planning\\nExecuting')).toBe('Planning\nExecuting');
  });

  it('normalizes escaped carriage returns', () => {
    expect(normalizeProgressStepText('Planning\\rExecuting')).toBe('Planning\nExecuting');
  });
});
