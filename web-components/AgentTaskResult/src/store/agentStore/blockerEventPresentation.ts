import type {
  StepDetailEntry,
  WSEvent,
} from '../../types';

const EXTERNAL_SERVICE_RESOLUTION_KINDS = new Set([
  'token_available',
  'token_missing',
  'client_unavailable',
  'token_response_timeout',
  'token_request_canceled',
]);

const EXTERNAL_SERVICE_FAILURE_KINDS = new Set([
  'token_missing',
  'client_unavailable',
  'token_response_timeout',
  'token_request_canceled',
]);

type ExternalServiceAccessPhase = 'waiting' | 'resolved' | 'failed';

export function isExternalServiceAccessWaiting(event: WSEvent): boolean {
  return event.event_type === 'agent_task_blocker_waiting' && event.kind === 'external_service_token';
}

export function requiresUserAttentionForAccess(event: WSEvent): boolean {
  const metadata = event.metadata as Record<string, unknown> | undefined;
  return event.user_action_required === true || metadata?.user_action_required === true;
}

export function isExternalServiceAccessResolved(event: WSEvent): boolean {
  return (
    event.event_type === 'agent_task_blocker_resolved' &&
    typeof event.kind === 'string' &&
    EXTERNAL_SERVICE_RESOLUTION_KINDS.has(event.kind)
  );
}

export function isExternalServiceAccessFailure(event: WSEvent): boolean {
  return typeof event.kind === 'string' && EXTERNAL_SERVICE_FAILURE_KINDS.has(event.kind);
}

export function buildExternalServiceAccessDetail(
  event: WSEvent,
  phase: ExternalServiceAccessPhase
): StepDetailEntry {
  const kind = typeof event.kind === 'string' ? event.kind : undefined;
  const connectionId =
    typeof event.connection_id === 'string' && event.connection_id.length > 0
      ? event.connection_id
      : 'unknown';
  const userActionRequired = requiresUserAttentionForAccess(event);
  const status =
    phase === 'failed'
      ? 'failed'
      : phase === 'resolved'
        ? 'completed'
        : 'waiting';

  if (phase === 'failed') {
    const body =
      typeof event.message === 'string' && event.message.trim().length > 0
        ? event.message
        : 'Basil could not retrieve the external-service token needed to continue this operation.';
    return {
      id: `external_service_access:${connectionId}`,
      type: 'step',
      timestamp: new Date().toISOString(),
      content: body,
      detail_kind: 'error',
      summary: 'External service access unavailable',
      body,
      metadata: {
        kind,
        connection_id: connectionId,
        status,
        user_action_required: userActionRequired,
      },
      streaming: false,
    };
  }

  const summary = userActionRequired
    ? 'Keychain access required'
    : phase === 'resolved'
      ? 'External service access ready'
      : 'Retrieving external service access';
  const body = userActionRequired
    ? 'Approve the macOS Keychain prompt so Basil can use this external-service connection.'
    : phase === 'resolved'
      ? 'Keychain returned the external-service token. Basil is continuing the operation.'
      : "Basil is requesting this connection's token from the local Keychain so it can continue the external-service operation.";

  return {
    id: `external_service_access:${connectionId}`,
    type: 'step',
    timestamp: new Date().toISOString(),
    content: body,
    detail_kind: phase === 'resolved' ? 'tool_result' : 'step_note',
    summary,
    body,
    metadata: {
      kind,
      connection_id: connectionId,
      status,
      user_action_required: userActionRequired,
    },
    streaming: false,
  };
}
