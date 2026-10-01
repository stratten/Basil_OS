import type { ProgressMetadata, ProgressStep, TimelineEntry, WSEvent } from '../../types';

export interface ParsedProgressEvent {
  currentPhase?: string;
  progressStep?: ProgressStep;
  timelineEntry?: TimelineEntry;
}

export function isTerminalProgressEvent(event: WSEvent): boolean {
  const eventType = event.event_type as string;
  const status = event.status as string | undefined;
  return (
    eventType === 'agent_task_result' ||
    eventType === 'agent_task_canceled' ||
    status === 'error' ||
    status === 'failed'
  );
}

export function isLiveProgressEvent(event: WSEvent): boolean {
  if (isTerminalProgressEvent(event)) return false;
  const eventType = event.event_type as string;
  return [
    'agent_task_progress',
    'agent_task_streaming',
    'agent_task_streaming_complete',
    'step_progress_update',
    'dynamic_step_added',
    'dynamic_step_updated',
    'agent_task_step_detail',
    'agent_progress_update',
    'checkpoint_waiting',
    'checkpoint_resumed',
    'session_context_info',
    'agent_task_blocker_waiting',
    'agent_task_blocker_resolved',
  ].includes(eventType);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function asMetadata(value: unknown): ProgressMetadata | undefined {
  return isRecord(value) ? value as ProgressMetadata : undefined;
}

function progressState(status: unknown): Pick<ProgressStep, 'isActive' | 'isComplete'> {
  const normalized = asText(status)?.toLowerCase();
  return {
    isActive: normalized === 'started' || normalized === 'running' || normalized === 'in_progress',
    isComplete: normalized === 'completed',
  };
}

function timelineEntryFromRecord(record: Record<string, unknown>): TimelineEntry | undefined {
  const content = asText(record.content) || asText(record.summary) || asText(record.step);
  if (!content) return undefined;

  const metadata = asMetadata(record.metadata);
  const type = asText(record.type);
  return {
    id: asText(record.id),
    type: type === 'thinking' || type === 'tool_start' || type === 'tool_complete' ? type : 'step',
    timestamp: asText(record.timestamp) || new Date().toISOString(),
    content,
    step_id: asText(record.step_id),
    correlation_id: asText(record.correlation_id),
    detail_kind: asText(record.detail_kind),
    summary: asText(record.summary),
    body: asText(record.body),
    metadata,
    streaming: record.streaming === true,
  };
}

function nestedEntry(event: WSEvent): Record<string, unknown> | undefined {
  if (isRecord(event.timeline_entry)) return event.timeline_entry;
  if (isRecord(event.entry)) return event.entry;
  if (isRecord(event.payload) && isRecord(event.payload.timeline_entry)) return event.payload.timeline_entry;
  if (isRecord(event.data) && isRecord(event.data.timeline_entry)) return event.data.timeline_entry;
  return undefined;
}

function legacyStep(event: WSEvent): string | undefined {
  if (typeof event.step === 'string') return asText(event.step);
  if (isRecord(event.step)) return asText(event.step.description) || asText(event.step.title);
  if (isRecord(event.dynamic_step)) return asText(event.dynamic_step.description) || asText(event.dynamic_step.title);
  if (isRecord(event.payload) && isRecord(event.payload.step)) {
    return asText(event.payload.step.description) || asText(event.payload.step.title);
  }
  return asText(event.message);
}

export function parseProgressEvent(event: WSEvent): ParsedProgressEvent {
  const entry = nestedEntry(event);
  const timelineEntry = entry ? timelineEntryFromRecord(entry) : undefined;
  const metadata = timelineEntry?.metadata;
  const phase = asText(metadata?.progress_phase) || asText(event.progress_phase);
  const step = asText(metadata?.progress_step) ||
    (metadata && timelineEntry ? timelineEntry.content : undefined) ||
    legacyStep(event);
  const status = metadata?.progress_status || metadata?.status || event.status;

  return {
    currentPhase: phase,
    timelineEntry,
    progressStep: step ? {
      id: timelineEntry?.id,
      step,
      ...progressState(status),
    } : undefined,
  };
}
