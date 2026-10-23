import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

function reportCards(parentAgentTaskId: string): WSEvent {
  return {
    event_type: 'delegated_provider_report_cards',
    agent_task_id: parentAgentTaskId,
    delegated_provider_report_cards: {
      parent_agent_task_id: parentAgentTaskId,
      items: [{
        delegated_agent_run_id: 'opaque-run-id',
        run_status: 'supervision_due',
        run_revision: 4,
        capture_state: 'available',
        evidence_count: 3,
        latest_summary: 'Provider completed this turn.',
        verification_state: 'not_applicable',
      }],
    },
  };
}

describe('AgentStore delegated provider report cards', () => {
  it('stores an identity-matched card without changing lifecycle', () => {
    const store = new AgentStore();
    store.registerAgent('parent-task');
    store.handleWSEvent(reportCards('parent-task'));

    expect(store.getAgent('parent-task')?.delegatedProviderReportCards).toEqual([{
      delegatedAgentRunId: 'opaque-run-id',
      runStatus: 'supervision_due',
      runRevision: 4,
      captureState: 'available',
      evidenceCount: 3,
      latestSummary: 'Provider completed this turn.',
      verificationState: 'not_applicable',
    }]);
    expect(store.getAgent('parent-task')?.status).toBe('routing');
  });

  it('maps an active follow-up card onto its root store entry', () => {
    const store = new AgentStore();
    store.registerAgent('root-task');
    const event = {
      ...reportCards('follow-up-task'),
      root_task_id: 'root-task',
    };
    store.handleWSEvent(event);

    expect(store.getAgent('root-task')?.delegatedProviderReportCards).toHaveLength(1);
    expect(store.getAgent('follow-up-task')).toBeUndefined();
  });

  it('ignores malformed and foreign-parent payloads without clearing a prior card', () => {
    const store = new AgentStore();
    store.registerAgent('parent-task');
    store.handleWSEvent(reportCards('parent-task'));

    store.handleWSEvent({
      ...reportCards('parent-task'),
      delegated_provider_report_cards: {
        parent_agent_task_id: 'other-task',
        items: [],
      },
    });
    store.handleWSEvent({
      ...reportCards('parent-task'),
      delegated_provider_report_cards: {
        parent_agent_task_id: 'parent-task',
        items: [{ delegated_agent_run_id: 'broken' }],
      },
    });

    expect(store.getAgent('parent-task')?.delegatedProviderReportCards).toHaveLength(1);
  });

  it('is idempotent and never revives a completed task', () => {
    const store = new AgentStore();
    store.registerAgent('parent-task');
    store.setResult('parent-task', 'Finished');
    const event = reportCards('parent-task');
    store.handleWSEvent(event);
    store.handleWSEvent(event);

    expect(store.getAgent('parent-task')?.status).toBe('completed');
    expect(store.getAgent('parent-task')?.delegatedProviderReportCards).toHaveLength(1);
  });
});
