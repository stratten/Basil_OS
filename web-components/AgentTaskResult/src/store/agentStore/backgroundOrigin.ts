/** Origins of runs that Basil starts on its own. A run like that must never take the reader away from what they are looking at or discard what they are typing. */
const BACKGROUND_ORIGIN_TYPES: ReadonlySet<string> = new Set(['scheduled_task', 'agent_follow_up', 'scheduled_follow_up']);

export function isBackgroundOriginType(originType: unknown): boolean {
  return typeof originType === 'string' && BACKGROUND_ORIGIN_TYPES.has(originType);
}

/** True for the `agent_task_origin` event that announces a run Basil started itself. The backend sends it before any other event of the run. */
export function isBackgroundStartEvent(eventType: string, event: object): boolean {
  return eventType === 'agent_task_origin' && isBackgroundOriginType((event as { origin_type?: unknown }).origin_type);
}
