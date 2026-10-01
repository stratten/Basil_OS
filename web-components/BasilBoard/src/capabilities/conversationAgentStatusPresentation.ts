import type { ConversationMessageItem, WSEvent } from '../contracts';

export type ConversationAgentTurnLifecycle =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'canceled';

export interface ConversationAgentTurnMetadata {
  route: 'agent_task';
  lifecycle: ConversationAgentTurnLifecycle;
  agentTaskId: string;
  statusText?: string;
  terminalOutcome?: string;
  narrationState?: string;
  requiresUserAttention: boolean;
  attentionId?: string;
}

const KNOWN_LIFECYCLES: ReadonlySet<string> = new Set([
  'pending',
  'running',
  'completed',
  'failed',
  'canceled',
]);

function isKnownLifecycle(value: unknown): value is ConversationAgentTurnLifecycle {
  return typeof value === 'string' && KNOWN_LIFECYCLES.has(value);
}

export function isTerminalConversationAgentStatusLifecycle(
  lifecycle: unknown,
): lifecycle is 'completed' | 'failed' | 'canceled' {
  return lifecycle === 'completed' || lifecycle === 'failed' || lifecycle === 'canceled';
}

export function conversationAgentTurnMetadata(
  message: ConversationMessageItem,
): ConversationAgentTurnMetadata | undefined {
  const raw = message.metadata?.conversation_turn;
  if (!raw || typeof raw !== 'object') return undefined;
  const turn = raw as Record<string, unknown>;
  if (turn.route !== 'agent_task') return undefined;
  if (!isKnownLifecycle(turn.lifecycle)) return undefined;
  const agentTaskId = turn.agent_task_id;
  if (typeof agentTaskId !== 'string' || !agentTaskId.trim()) return undefined;
  const statusText = typeof turn.status_text === 'string' ? turn.status_text : undefined;
  const terminalOutcome = typeof turn.terminal_outcome === 'string' ? turn.terminal_outcome : undefined;
  const requiresUserAttention = turn.requires_user_attention === true;
  const attentionId = typeof turn.attention_id === 'string' && turn.attention_id.trim()
    ? turn.attention_id
    : undefined;
  const narration = turn.narration;
  const narrationState = narration && typeof narration === 'object'
    && typeof (narration as Record<string, unknown>).lifecycle === 'string'
    ? (narration as Record<string, string>).lifecycle
    : undefined;
  return {
    route: 'agent_task',
    lifecycle: turn.lifecycle,
    agentTaskId,
    statusText,
    terminalOutcome,
    narrationState,
    requiresUserAttention,
    attentionId,
  };
}

export function shouldShowAgentTaskStatusCard(message: ConversationMessageItem): boolean {
  return Boolean(conversationAgentTurnMetadata(message));
}

export function isValidAgentStatusEvent(event: WSEvent): event is WSEvent & {
  conversation_id: string;
  placeholder_message_id: string;
  agent_task_id: string;
  lifecycle: ConversationAgentTurnLifecycle;
} {
  return (
    event.event_type === 'conversation_agent_status'
    && typeof event.conversation_id === 'string' && event.conversation_id.trim().length > 0
    && typeof event.placeholder_message_id === 'string' && event.placeholder_message_id.trim().length > 0
    && typeof event.agent_task_id === 'string' && event.agent_task_id.trim().length > 0
    && isKnownLifecycle(event.lifecycle)
    && (event.requires_user_attention === undefined || typeof event.requires_user_attention === 'boolean')
    && (event.attention_id === undefined || (typeof event.attention_id === 'string' && event.attention_id.trim().length > 0))
    && (event.attention_id === undefined || event.requires_user_attention === true)
    && (event.requires_user_attention !== true || (typeof event.attention_id === 'string' && event.attention_id.trim().length > 0))
  );
}

export function buildAgentTaskPlaceholderMessage(event: WSEvent): ConversationMessageItem {
  if (!isValidAgentStatusEvent(event)) {
    throw new Error('buildAgentTaskPlaceholderMessage requires a valid conversation_agent_status event');
  }
  return {
    id: event.placeholder_message_id,
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    metadata: {
      conversation_turn: {
        route: 'agent_task',
        lifecycle: event.lifecycle,
        agent_task_id: event.agent_task_id,
        terminal_outcome: event.terminal_outcome ?? null,
        status_text: event.status_text ?? null,
        requires_user_attention: event.requires_user_attention === true,
        ...(typeof event.attention_id === 'string' && event.attention_id.trim()
          ? { attention_id: event.attention_id }
          : {}),
        narration: { lifecycle: event.narration_state ?? 'pending' },
      },
    },
  };
}

function preservedActivitySummary(message: ConversationMessageItem): Record<string, unknown> {
  const rawTurn = message.metadata.conversation_turn;
  if (!rawTurn || typeof rawTurn !== 'object' || Array.isArray(rawTurn)) return {};
  const turn = rawTurn as Record<string, unknown>;
  if (!Object.prototype.hasOwnProperty.call(turn, 'activity_summary')) return {};
  return {
    activity_summary: turn.activity_summary,
    ...(Object.prototype.hasOwnProperty.call(turn, 'activity_summary_fingerprint')
      ? { activity_summary_fingerprint: turn.activity_summary_fingerprint }
      : {}),
  };
}

export function mergeAgentStatusIntoMessage(
  message: ConversationMessageItem,
  event: WSEvent,
): ConversationMessageItem {
  if (!isValidAgentStatusEvent(event)) return message;
  const current = conversationAgentTurnMetadata(message);
  if (
    current
    && isTerminalConversationAgentStatusLifecycle(current.lifecycle)
    && current.lifecycle !== event.lifecycle
  ) {
    return message;
  }
  if (current && current.agentTaskId !== event.agent_task_id) {
    return message;
  }
  const activitySummary = preservedActivitySummary(message);
  return {
    ...message,
    metadata: {
      ...message.metadata,
      conversation_turn: {
        route: 'agent_task',
        lifecycle: event.lifecycle,
        agent_task_id: event.agent_task_id,
        terminal_outcome: event.terminal_outcome ?? null,
        status_text: event.status_text ?? null,
        requires_user_attention: event.requires_user_attention === true,
        ...activitySummary,
        ...(typeof event.attention_id === 'string' && event.attention_id.trim()
          ? { attention_id: event.attention_id }
          : {}),
        narration: { lifecycle: event.narration_state ?? current?.narrationState ?? 'pending' },
      },
    },
  };
}
