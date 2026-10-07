import type { WSEvent } from '../contracts';

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
