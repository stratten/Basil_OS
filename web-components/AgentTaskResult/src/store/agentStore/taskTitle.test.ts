import { describe, expect, it } from 'vitest';
import type { AgentTaskPresentationSummary } from '../../artifacts/artifactContract';
import { AgentStore } from './websocketHandlers';

describe('AgentStore generated task title', () => {
  it('stores the first nonblank backend title and keeps it stable', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.updateAgentTaskTitle('task-1', '  Folder Size Investigation  ');
    store.updateAgentTaskTitle('task-1', 'Replacement title');

    expect(store.getAgent('task-1')?.taskTitle).toBe('Folder Size Investigation');
  });

  it('does not create a title from blank backend data', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.updateAgentTaskTitle('task-1', '   ');

    expect(store.getAgent('task-1')?.taskTitle).toBeUndefined();
  });

  it('seeds a historical root title into a fresh follow-up state', () => {
    const store = new AgentStore();

    store.beginFollowUpTurn(
      'follow-up-1',
      'root-task',
      undefined,
      'root-task',
      'Downloads Folder Cleanup Plan',
    );

    expect(store.getAgent('root-task')?.taskTitle).toBe('Downloads Folder Cleanup Plan');
  });

  it('does not replace an already-live root title during follow-up setup', () => {
    const store = new AgentStore();
    store.registerAgent('root-task');
    store.updateAgentTaskTitle('root-task', 'Original Root Title');

    store.beginFollowUpTurn(
      'follow-up-1',
      'root-task',
      undefined,
      'root-task',
      'Replacement Root Title',
    );

    expect(store.getAgent('root-task')?.taskTitle).toBe('Original Root Title');
  });

  const presentationSummary: AgentTaskPresentationSummary = {
    agentTaskId: 'root-task',
    lifecycle: 'completed',
    workflow: {},
    artifacts: [],
    artifactCount: 0,
    verificationStatus: 'resolved',
    requiresUserAttention: false,
    delegatedProviderReportCards: [],
  };

  it('clears the prior turn summary for both retry and follow-up transitions', () => {
    const store = new AgentStore();
    store.registerAgent('root-task');
    store.setPresentationSummary('root-task', presentationSummary);
    store.resetForRetry('root-task');

    expect(store.getAgent('root-task')?.presentationSummary).toBeUndefined();
    expect(store.getAgent('root-task')?.delegatedProviderReportCards).toEqual([]);

    store.setPresentationSummary('root-task', presentationSummary);
    store.setDelegatedProviderReportCards('root-task', [{
      delegatedAgentRunId: 'run-1',
      runStatus: 'settled',
      runRevision: 1,
      captureState: 'available',
      evidenceCount: 2,
      verificationState: 'verified',
    }]);
    store.beginFollowUpTurn('follow-up-1', 'root-task');

    expect(store.getAgent('root-task')?.presentationSummary).toBeUndefined();
    expect(store.getAgent('root-task')?.delegatedProviderReportCards).toEqual([]);
  });
});
