import { describe, expect, it } from 'vitest';
import { deriveRunPhase, isActivityInCard, showsRunStatusCard, type RunPhaseInput } from './runPhase';

const base: RunPhaseInput = {
  status: 'completed',
  isStreaming: false,
};

describe('deriveRunPhase', () => {
  it('reports in-flight statuses as working and busy', () => {
    for (const status of ['capturing', 'routing', 'processing']) {
      const phase = deriveRunPhase({ ...base, status });
      expect(phase.kind).toBe('working');
      expect(phase.isBusy).toBe(true);
      expect(phase.offersRecovery).toBe(false);
    }
  });

  it('keeps paused and awaiting input distinct and not busy', () => {
    expect(deriveRunPhase({ ...base, status: 'paused' })).toMatchObject({ kind: 'paused', isBusy: false });
    expect(deriveRunPhase({ ...base, status: 'awaitingInput' })).toMatchObject({ kind: 'awaiting', isBusy: false });
  });

  it('treats a terminal task with pending verification as verifying with no recovery offered', () => {
    for (const status of ['completed', 'failed']) {
      const phase = deriveRunPhase({
        ...base,
        status,
        verificationStatus: 'pending',
        errorMessage: status === 'failed' ? 'provisional failure' : undefined,
      });
      expect(phase.kind).toBe('verifying');
      expect(phase.isBusy).toBe(true);
      expect(phase.offersRecovery).toBe(false);
      expect(phase.outcome).toBeNull();
    }
  });

  it('settles to the resolved outcome once verification is no longer pending', () => {
    expect(deriveRunPhase({ ...base, verificationStatus: 'resolved' })).toMatchObject({ kind: 'settled', outcome: 'success' });
    expect(deriveRunPhase({ ...base, status: 'failed', errorMessage: 'boom', resultSeverity: 'error' })).toMatchObject({
      kind: 'settled',
      outcome: 'failed',
      offersRecovery: true,
    });
    expect(deriveRunPhase({ ...base, outcome: 'partial' })).toMatchObject({ kind: 'settled', outcome: 'partial', label: 'Partial result' });
    expect(deriveRunPhase({ ...base, errorMessage: 'some left', resultSeverity: 'warning' })).toMatchObject({ outcome: 'partial' });
  });

  it('treats completed_with_warnings as a clean success even with stale error residue', () => {
    expect(deriveRunPhase({ ...base, outcome: 'completed_with_warnings', errorMessage: 'old retry detail' })).toMatchObject({
      kind: 'settled',
      outcome: 'success',
      offersRecovery: false,
    });
  });

  it('gives canceled precedence over the failed status the store uses to represent it', () => {
    const phase = deriveRunPhase({ ...base, status: 'failed', isCanceled: true, errorMessage: 'Task canceled', verificationStatus: 'pending' });
    expect(phase).toMatchObject({ kind: 'canceled', label: 'Canceled', isBusy: false, offersRecovery: true });
  });

  it('routes activity and the status card by phase', () => {
    expect(isActivityInCard(deriveRunPhase({ ...base, status: 'processing' }))).toBe(true);
    expect(isActivityInCard(deriveRunPhase({ ...base, verificationStatus: 'pending' }))).toBe(true);
    expect(isActivityInCard(deriveRunPhase(base))).toBe(false);
    expect(showsRunStatusCard(deriveRunPhase(base))).toBe(false);
    expect(showsRunStatusCard(deriveRunPhase({ ...base, status: 'failed', errorMessage: 'x' }))).toBe(true);
    expect(showsRunStatusCard(deriveRunPhase({ ...base, isCanceled: true }))).toBe(true);
  });
});
