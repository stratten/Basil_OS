import type { AgentTaskActiveIndicatorStatus } from '@shared/AgentTaskActiveIndicator';

const RUNNING_STATUSES = new Set([
  'capturing',
  'routing',
  'processing',
  'awaiting_provider_delegation',
  'awaiting_delegated_agents',
]);

const AWAITING_INPUT_STATUSES = new Set([
  'awaiting_user_input',
  'waiting_user_input',
  'needs_clarification',
]);

/** Maps a backend Agent Task status onto the glyph the Agent Task sidebar row shows for that state.
 * Returns null for terminal or unrecognized statuses, which keep their own result icons. */
export function agentTaskIndicatorStatus(status: string): AgentTaskActiveIndicatorStatus | null {
  if (RUNNING_STATUSES.has(status)) return 'processing';
  if (status === 'paused') return 'paused';
  if (AWAITING_INPUT_STATUSES.has(status)) return 'awaitingInput';
  return null;
}
