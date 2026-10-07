import { describe, expect, it } from 'vitest';
import { isTerminalAgentTaskEvent, rejectUnknownTabKind } from './homeReducer';

describe('homeReducer', () => {
  it('identifies only terminal agent-task websocket events', () => {
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_progress',
      agent_task_id: 'task-1',
      status: 'running',
    })).toBe(false);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      status: 'completed',
    })).toBe(true);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      agent_task_id: 'task-1',
      success: false,
    })).toBe(true);
    expect(isTerminalAgentTaskEvent({
      event_type: 'agent_task_result',
      status: 'completed',
    })).toBe(false);
  });

  it('rejects unknown tab kinds', () => {
    expect(rejectUnknownTabKind('home')).toBe(false);
    expect(rejectUnknownTabKind('capability')).toBe(false);
    expect(rejectUnknownTabKind('system_embed')).toBe(false);
    expect(rejectUnknownTabKind('agent_report')).toBe(false);
    expect(rejectUnknownTabKind('custom_html')).toBe(true);
  });
});
