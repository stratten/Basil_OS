import { describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { AgentStore } from './websocketHandlers';

describe('AgentStore provider permission approval handling', () => {
  it('stores provider_permission metadata from execution_approval_request events', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    const event: WSEvent = {
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'permission-1',
      command: 'Run `rm -rf /tmp/scratch`?',
      reason: 'The provider wants to delete a scratch directory.',
      risk_level: 'medium',
      execution_type: 'provider_permission',
      provider_permission: {
        interaction_id: 'permission-1',
        provider_run_id: 'run-1',
        agent_task_id: 'task-1',
        subject: { type: 'command', command: 'rm -rf /tmp/scratch', cwd: '/tmp' },
        allow_option_id: 'allow-once',
        reject_option_id: 'reject-once',
      },
    };
    store.handleWSEvent(event);

    const agent = store.getAgent('task-1');
    expect(agent?.showApprovalPrompt).toBe(true);
    expect(agent?.approvalRequests[0]?.execution_type).toBe('provider_permission');
    expect(agent?.approvalRequests[0]?.provider_permission).toEqual({
      interaction_id: 'permission-1',
      provider_run_id: 'run-1',
      agent_task_id: 'task-1',
      subject: { type: 'command', command: 'rm -rf /tmp/scratch', cwd: '/tmp' },
      allow_option_id: 'allow-once',
      reject_option_id: 'reject-once',
    });
  });

  it('clears stale approval and checkpoint presentation before retrying', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.handleWSEvent({
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'approval-1',
      command: 'Open Outlook',
      reason: 'Foreground automation needs approval.',
      risk_level: 'medium',
      execution_type: 'applescript',
    });

    store.showCheckpoint('task-1', {
      checkpoint_id: 'checkpoint-1',
      session_agent_task_id: 'task-1',
      prompt: 'Choose an option',
      input_type: 'choice',
      options: [{ id: 'option-1', label: 'Continue', value: 'continue' }],
    });

    store.resetForRetry('task-1');

    const agent = store.getAgent('task-1');
    expect(agent?.status).toBe('processing');
    expect(agent?.showApprovalPrompt).toBe(false);
    expect(agent?.approvalRequests).toEqual([]);
    expect(agent?.showCheckpointPrompt).toBe(false);
    expect(agent?.currentCheckpoint).toBeUndefined();
    expect(agent?.inlineCheckpoint).toBeUndefined();
  });

  it('shows a fresh approval request for a new approval_id after a denial left the task failed', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.handleWSEvent({
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'approval-1',
      command: 'python3 server.py --host 127.0.0.1 --port 43123',
      reason: 'Starting a local server needs approval.',
      risk_level: 'medium',
      execution_type: 'shell',
    });
    store.hideApproval('task-1');
    store.handleWSEvent({
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'task-1',
      success: false,
      outcome_reason: 'Command denied by user',
    });

    const deniedAgent = store.getAgent('task-1');
    expect(deniedAgent?.status).toBe('failed');
    expect(deniedAgent?.showApprovalPrompt).toBe(false);

    store.handleWSEvent({
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'approval-2',
      command: 'python3 server.py --host 127.0.0.1 --port 43123',
      reason: 'Starting a local server needs approval.',
      risk_level: 'medium',
      execution_type: 'shell',
    });

    const retriedAgent = store.getAgent('task-1');
    expect(retriedAgent?.showApprovalPrompt).toBe(true);
    expect(retriedAgent?.approvalRequests).toMatchObject([{ approval_id: 'approval-2' }]);
    expect(retriedAgent?.status).toBe('awaitingInput');
  });

  it('suppresses a replayed execution_approval_request for an approval_id already handled on a finished task', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    const event: WSEvent = {
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'approval-1',
      command: 'Open Outlook',
      reason: 'Foreground automation needs approval.',
      risk_level: 'medium',
      execution_type: 'applescript',
    };
    store.handleWSEvent(event);
    store.hideApproval('task-1');
    store.handleWSEvent({
      event_type: 'agent_task_outcome_update',
      agent_task_id: 'task-1',
      success: false,
      outcome_reason: 'Command denied by user',
    });

    // A buffered re-send of the exact same already-decided approval_id
    // (e.g. on window reopen) must not resurrect the overlay.
    store.handleWSEvent(event);

    const agent = store.getAgent('task-1');
    expect(agent?.showApprovalPrompt).toBe(false);
    expect(agent?.status).toBe('failed');
  });

  it('keeps simultaneous approval requests independently visible', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    for (const approval_id of ['approval-1', 'approval-2']) {
      store.handleWSEvent({
        event_type: 'execution_approval_request',
        agent_task_id: 'task-1',
        approval_id,
        command: `mdfind ${approval_id}`,
        reason: 'Spotlight search requires approval.',
        risk_level: 'low',
        execution_type: 'shell',
      });
    }

    store.removeApproval('task-1', 'approval-1');

    expect(store.getAgent('task-1')?.approvalRequests).toMatchObject([
      { approval_id: 'approval-2' },
    ]);
    expect(store.getAgent('task-1')?.showApprovalPrompt).toBe(true);
  });
});

describe('AgentStore command input requests', () => {
  it('stores command_input metadata and shows a waiting-for-input step', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    const event: WSEvent = {
      event_type: 'execution_approval_request',
      agent_task_id: 'task-1',
      approval_id: 'command-input-1',
      command: 'sudo ls',
      reason: 'The command is asking for input: Password:',
      risk_level: 'medium',
      execution_type: 'command_input',
      command_input: {
        request_id: 'command-input-1',
        agent_task_id: 'task-1',
        prompt: 'Password:',
        secret: true,
        command: 'sudo ls',
        created_at: 1_800_000_000,
        expires_at: 1_800_000_300,
      },
    };
    store.handleWSEvent(event);

    const agent = store.getAgent('task-1');
    expect(agent?.showApprovalPrompt).toBe(true);
    expect(agent?.approvalRequests[0]?.execution_type).toBe('command_input');
    expect(agent?.approvalRequests[0]?.command_input).toMatchObject({
      request_id: 'command-input-1',
      prompt: 'Password:',
      secret: true,
    });
  });
});
