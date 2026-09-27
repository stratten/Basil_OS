import { describe, expect, it } from 'vitest';
import { isUserFacingResponseStreaming, normalizeResultForPresentation } from './resultContentUtils';

describe('user-facing response streaming', () => {
  it('begins only with a streaming visible result', () => {
    expect(isUserFacingResponseStreaming(true, 'First visible token')).toBe(true);
    expect(isUserFacingResponseStreaming(true, '')).toBe(false);
    expect(isUserFacingResponseStreaming(false, 'Completed response')).toBe(false);
  });
});

describe('legacy result presentation', () => {
  it('removes only the obsolete completed-with-warnings prefix', () => {
    expect(normalizeResultForPresentation(
      'Completed with warnings: The requested work was delivered.',
      'completed_with_warnings',
    )).toBe('The requested work was delivered.');
    expect(normalizeResultForPresentation(
      'Partial result: Some requested work remains.',
      'partial',
    )).toBe('Partial result: Some requested work remains.');
  });
});
