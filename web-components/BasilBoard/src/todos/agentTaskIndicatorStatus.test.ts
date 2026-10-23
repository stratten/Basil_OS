import { describe, expect, it } from 'vitest';
import { agentTaskIndicatorStatus } from './agentTaskIndicatorStatus';

describe('agentTaskIndicatorStatus', () => {
  it.each([
    ['capturing', 'processing'],
    ['routing', 'processing'],
    ['processing', 'processing'],
    ['awaiting_provider_delegation', 'processing'],
    ['awaiting_delegated_agents', 'processing'],
    ['paused', 'paused'],
    ['awaiting_user_input', 'awaitingInput'],
    ['waiting_user_input', 'awaitingInput'],
    ['needs_clarification', 'awaitingInput'],
  ])('maps %s to %s', (status, expected) => {
    expect(agentTaskIndicatorStatus(status)).toBe(expected);
  });

  it.each(['completed', 'failed', 'canceled', '', 'mystery_state'])('returns null for %s', (status) => {
    expect(agentTaskIndicatorStatus(status)).toBeNull();
  });
});
