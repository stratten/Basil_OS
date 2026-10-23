import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ScheduledRunHistoryList from './ScheduledRunHistoryList';
import type { ScheduledAgentTaskRun } from '../../types';

function run(overrides: Partial<ScheduledAgentTaskRun>): ScheduledAgentTaskRun {
  return {
    id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: 'task-1',
    scheduled_for: '2026-10-22T10:00:00Z',
    started_at: '2026-10-22T10:00:01Z',
    status: 'completed',
    created_at: '2026-10-22T10:00:00Z',
    ...overrides,
  };
}

function render(overrides: Partial<ScheduledAgentTaskRun>) {
  return renderToStaticMarkup(<ScheduledRunHistoryList runs={[run(overrides)]} />);
}

describe('ScheduledRunHistoryList status language', () => {
  it('draws a partial result with the shared half-filled mark and the shared label', () => {
    const markup = render({ agent_task_status: 'failed', outcome: 'partial', verification_status: 'resolved', notice: 'Partial result: two of three feeds loaded' });

    expect(markup).toContain('run-status-dot--partial outcome-partial-mark');
    expect(markup).toContain('Partial result');
    expect(markup).toContain('Partial result: two of three feeds loaded');
    expect(markup).not.toContain('run-status-dot--danger');
  });

  it('draws a real failure with the failure dot and the shared label', () => {
    const markup = render({ status: 'failed', agent_task_status: 'failed', outcome: 'failed', verification_status: 'resolved', error_message: 'The feed was unreachable' });

    expect(markup).toContain('run-status-dot--danger');
    expect(markup).toContain('Couldn&#x27;t complete');
    expect(markup).toContain('The feed was unreachable');
  });

  it('draws a verified success and a result still being verified differently', () => {
    expect(render({ agent_task_status: 'completed', outcome: 'success', verification_status: 'resolved' })).toContain('run-status-dot--success');
    const verifying = render({ status: 'running', agent_task_status: 'failed', outcome: 'partial', verification_status: 'pending' });
    expect(verifying).toContain('execution-live-beacon');
    expect(verifying).toContain('Verifying the outcome');
  });

  it('keeps the run status word for a run that never reached an agent task', () => {
    const markup = render({ status: 'missed', agent_task_id: null, started_at: null });

    expect(markup).toContain('missed');
    expect(markup).not.toContain('run-status-dot');
  });
});
