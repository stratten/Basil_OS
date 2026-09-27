import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import {
  buildExternalServiceAccessDetail,
  isExternalServiceAccessFailure,
  isExternalServiceAccessWaiting,
  requiresUserAttentionForAccess,
} from './blockerEventPresentation';

describe('blockerEventPresentation', () => {
  it('maps background external-service token waits to non-error details', () => {
    const event: WSEvent = {
      event_type: 'agent_task_blocker_waiting',
      kind: 'external_service_token',
      connection_id: 'conn-1',
    };

    const detail = buildExternalServiceAccessDetail(event, 'waiting');

    expect(isExternalServiceAccessWaiting(event)).toBe(true);
    expect(requiresUserAttentionForAccess(event)).toBe(false);
    expect(detail.detail_kind).toBe('step_note');
    expect(detail.summary).toBe('Retrieving external service access');
    expect(detail.metadata).toMatchObject({
      status: 'waiting',
      user_action_required: false,
    });
  });

  it('maps user-facing Keychain waits to attention-required details', () => {
    const event: WSEvent = {
      event_type: 'agent_task_blocker_waiting',
      kind: 'external_service_token',
      connection_id: 'conn-1',
      user_action_required: true,
    };

    const detail = buildExternalServiceAccessDetail(event, 'waiting');

    expect(requiresUserAttentionForAccess(event)).toBe(true);
    expect(detail.detail_kind).toBe('step_note');
    expect(detail.summary).toBe('Keychain access required');
    expect(detail.metadata).toMatchObject({
      status: 'waiting',
      user_action_required: true,
    });
  });

  it('maps available tokens to completed tool results', () => {
    const event: WSEvent = {
      event_type: 'agent_task_blocker_resolved',
      kind: 'token_available',
      connection_id: 'conn-1',
    };

    const detail = buildExternalServiceAccessDetail(event, 'resolved');

    expect(detail.detail_kind).toBe('tool_result');
    expect(detail.summary).toBe('External service access ready');
    expect(detail.metadata).toMatchObject({ status: 'completed' });
  });

  it('maps missing tokens to failed error details', () => {
    const event: WSEvent = {
      event_type: 'agent_task_blocker_resolved',
      kind: 'token_missing',
      connection_id: 'conn-1',
      message: 'Token is gone.',
    };

    const detail = buildExternalServiceAccessDetail(event, 'failed');

    expect(isExternalServiceAccessFailure(event)).toBe(true);
    expect(detail.detail_kind).toBe('error');
    expect(detail.summary).toBe('External service access unavailable');
    expect(detail.body).toBe('Token is gone.');
    expect(detail.metadata).toMatchObject({ status: 'failed' });
  });

  it('does not classify generic blockers as external service access', () => {
    const event: WSEvent = {
      event_type: 'agent_task_blocker_waiting',
      kind: 'generic_wait',
    };

    expect(isExternalServiceAccessWaiting(event)).toBe(false);
  });
});
