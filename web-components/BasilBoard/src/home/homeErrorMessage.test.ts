import { describe, expect, it } from 'vitest';
import { homeErrorMessage } from './homeErrorMessage';

describe('homeErrorMessage', () => {
  it('unwraps a FastAPI detail string', () => {
    expect(homeErrorMessage(new Error('{"detail":"Router unavailable"}'), 'fallback')).toBe('Router unavailable');
  });

  it('falls back when the detail is structured rather than text', () => {
    expect(homeErrorMessage(new Error('{"detail":[{"msg":"bad"}]}'), 'fallback')).toBe('fallback');
  });

  it('keeps plain text messages', () => {
    expect(homeErrorMessage(new Error('Network down'), 'fallback')).toBe('Network down');
  });

  it('keeps JSON without a detail field as text', () => {
    expect(homeErrorMessage(new Error('{"error":"x"}'), 'fallback')).toBe('{"error":"x"}');
  });

  it('uses the fallback for empty messages and non-errors', () => {
    expect(homeErrorMessage(new Error('  '), 'fallback')).toBe('fallback');
    expect(homeErrorMessage('boom', 'fallback')).toBe('fallback');
  });
});
