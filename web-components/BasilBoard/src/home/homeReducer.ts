import type { HomeTimelineItem, HomeTurnResponse, WSEvent } from '../contracts';

export interface HomeUiState {
  timeline: HomeTimelineItem[];
  submitting: boolean;
  error?: string;
  voiceState: 'idle' | 'starting' | 'recording' | 'processing' | 'error';
  voiceError?: string;
}

export const initialHomeUiState: HomeUiState = {
  timeline: [],
  submitting: false,
  voiceState: 'idle',
};

export function applyHydrationTimeline(timeline: HomeTimelineItem[]): HomeUiState {
  return {
    ...initialHomeUiState,
    timeline,
  };
}

export function applyTurnResponse(
  state: HomeUiState,
  response: HomeTurnResponse,
  optimisticUser: Extract<HomeTimelineItem, { kind: 'user_message' }>,
): HomeUiState {
  const nextTimeline = [...state.timeline];
  const createdAt = optimisticUser.createdAt;

  if (!nextTimeline.some((item) => item.kind === 'user_message' && item.messageId === response.user_message_id)) {
    nextTimeline.push(optimisticUser);
  }

  if (response.route_kind === 'conversation' && response.assistant_message_id && response.assistant_content) {
    nextTimeline.push({
      kind: 'conversation_answer',
      messageId: response.assistant_message_id,
      inReplyTo: response.user_message_id,
      content: response.assistant_content,
      createdAt,
    });
  }

  if (response.route_kind === 'agent_task' && response.agent_task_id) {
    nextTimeline.push({
      kind: 'agent_task',
      messageId: response.user_message_id,
      inReplyTo: response.user_message_id,
      agentTaskId: response.agent_task_id,
      state: mapTurnState(response.state),
      createdAt,
    });
  }

  return {
    ...state,
    timeline: mergeTimelineItems(state.timeline, nextTimeline),
    submitting: false,
    error: undefined,
  };
}

export function applyReconciledTurn(state: HomeUiState, response: HomeTurnResponse): HomeUiState {
  if (response.route_kind !== 'agent_task' || !response.agent_task_id) {
    return state;
  }

  const taskState = mapTurnState(response.state);
  const taskExists = state.timeline.some(
    (item) => item.kind === 'agent_task' && item.agentTaskId === response.agent_task_id,
  );
  const timeline = taskExists
    ? state.timeline.map((item) => (
      item.kind === 'agent_task' && item.agentTaskId === response.agent_task_id
        ? { ...item, state: taskState }
        : item
    ))
    : [
      ...state.timeline,
      {
        kind: 'agent_task' as const,
        messageId: response.user_message_id,
        inReplyTo: response.user_message_id,
        agentTaskId: response.agent_task_id,
        state: taskState,
        createdAt: new Date().toISOString(),
      },
    ];

  return { ...state, timeline };
}

export function applyWsEvent(state: HomeUiState, event: WSEvent): HomeUiState {
  if (!event.agent_task_id) return state;
  const nextTimeline = state.timeline.map((item) => {
    if (item.kind !== 'agent_task' || item.agentTaskId !== event.agent_task_id) {
      return item;
    }
    const nextState = mapAgentTaskEventState(event);
    return {
      ...item,
      state: nextState ?? item.state,
      result: typeof event.result === 'string'
        ? event.result
        : typeof event.error === 'string'
          ? event.error
          : item.result,
      outcome: typeof event.outcome === 'string' ? event.outcome : item.outcome,
    };
  });
  return { ...state, timeline: nextTimeline };
}

export function mergeTimelineItems(
  existing: HomeTimelineItem[],
  incoming: HomeTimelineItem[],
): HomeTimelineItem[] {
  const byKey = new Map<string, HomeTimelineItem>();
  for (const item of existing) {
    byKey.set(timelineKey(item), item);
  }
  for (const item of incoming) {
    byKey.set(timelineKey(item), item);
  }
  return Array.from(byKey.values());
}

export function timelineKey(item: HomeTimelineItem): string {
  if (item.kind === 'conversation_answer') return item.messageId;
  if (item.kind === 'agent_task') return `agent-task:${item.agentTaskId}`;
  return item.messageId;
}

export function mapTurnState(
  state: HomeTurnResponse['state'],
): 'queued' | 'running' | 'completed' | 'failed' | 'canceled' {
  if (state === 'routing') return 'queued';
  if (state === 'running') return 'running';
  if (state === 'completed') return 'completed';
  if (state === 'failed') return 'failed';
  return 'canceled';
}

function mapAgentTaskEventState(
  event: WSEvent,
): 'queued' | 'running' | 'completed' | 'failed' | 'canceled' | undefined {
  const eventType = event.event_type ?? '';
  if (event.success === false || event.status === 'failed') return 'failed';
  if (event.status === 'canceled') return 'canceled';
  if (eventType === 'agent_task_result' || event.status === 'completed') return 'completed';
  if (eventType === 'agent_task_progress') return 'running';
  return undefined;
}

export function isTerminalAgentTaskEvent(event: WSEvent): boolean {
  if (!event.agent_task_id) return false;
  return (
    event.event_type === 'agent_task_result'
    || event.success === false
    || event.status === 'completed'
    || event.status === 'failed'
    || event.status === 'canceled'
  );
}

export function rejectUnknownTabKind(tabKind: string): boolean {
  return !['home', 'capability', 'system_embed', 'agent_report'].includes(tabKind);
}
