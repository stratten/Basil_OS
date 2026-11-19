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

  describe('agent_task_title event', () => {
    function titleEvent(agentTaskId: string, title: unknown) {
      return { event_type: 'agent_task_title' as const, agent_task_id: agentTaskId, title };
    }

    it('names the task the window already shows, replacing the prompt text in the sidebar', () => {
      const store = new AgentStore();
      store.registerAgent('task-1', "Complete this to-do on the user's behalf: triage the inbox");

      store.handleWSEvent(titleEvent('task-1', 'Weekly Inbox Triage'));

      expect(store.getAgent('task-1')?.taskTitle).toBe('Weekly Inbox Triage');
    });

    it('keeps the first title the task received', () => {
      const store = new AgentStore();
      store.registerAgent('task-1');
      store.updateAgentTaskTitle('task-1', 'Original Title');

      store.handleWSEvent(titleEvent('task-1', 'Later Title'));

      expect(store.getAgent('task-1')?.taskTitle).toBe('Original Title');
    });

    it('does not open, register or select a task this window does not hold', () => {
      const store = new AgentStore();
      store.registerAgent('task-1');
      const before = store.getAllAgents().map((agent) => agent.agentTaskId);

      store.handleWSEvent(titleEvent('unknown-task', 'Stray Title'));

      expect(store.getAgent('unknown-task')).toBeUndefined();
      expect(store.getAllAgents().map((agent) => agent.agentTaskId)).toEqual(before);
      expect(store.getSelectedAgentId()).toBe('task-1');
    });

    it('ignores a follow-up turn title, which belongs to a different request than the chain title', () => {
      const store = new AgentStore();
      store.beginFollowUpTurn('follow-up-1', 'root-task');

      store.handleWSEvent(titleEvent('follow-up-1', 'Follow-up Title'));

      expect(store.getAgent('root-task')?.taskTitle).toBeUndefined();
    });

    it('ignores a missing or blank title', () => {
      const store = new AgentStore();
      store.registerAgent('task-1');

      store.handleWSEvent(titleEvent('task-1', undefined));
      store.handleWSEvent(titleEvent('task-1', '   '));

      expect(store.getAgent('task-1')?.taskTitle).toBeUndefined();
    });
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
