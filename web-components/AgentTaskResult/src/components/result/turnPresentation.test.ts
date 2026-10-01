import { describe, expect, it } from 'vitest';
import { resolveTurnStatus } from './turnPresentation';

describe('resolveTurnStatus', () => {
  it('maps live statuses to active', () => {
    expect(resolveTurnStatus({ status: 'processing' })).toBe('active');
    expect(resolveTurnStatus({ status: 'awaitingInput' })).toBe('active');
  });

  it('reports failures, including older turns without an explicit status', () => {
    expect(resolveTurnStatus({ status: 'failed' })).toBe('failed');
    expect(resolveTurnStatus({ status: 'canceled' })).toBe('failed');
    expect(resolveTurnStatus({ errorMessage: 'The tool crashed.' })).toBe('failed');
    expect(resolveTurnStatus({ status: 'completed', outcome: 'failure' })).toBe('failed');
  });

  it('reports partial outcomes the same way the run rail does', () => {
    expect(resolveTurnStatus({ status: 'failed', outcome: 'partial' })).toBe('partial');
    expect(resolveTurnStatus({ status: 'completed', outcome: 'completed_with_warnings', errorMessage: 'Minor issue' })).toBe('partial');
    expect(resolveTurnStatus({ errorMessage: 'Some work remains', resultSeverity: 'warning' })).toBe('partial');
  });

  it('defaults to success', () => {
    expect(resolveTurnStatus({ status: 'completed' })).toBe('success');
    expect(resolveTurnStatus({})).toBe('success');
  });
});
