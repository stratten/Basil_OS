// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ExecutionApprovalRequest } from '../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const submitApprovalDecision = vi.fn();
const submitBrowserSensitiveFillApproval = vi.fn();
const submitProviderPermissionDecision = vi.fn();

vi.mock('../services/api', () => ({
  submitApprovalDecision,
  submitBrowserSensitiveFillApproval,
  submitProviderPermissionDecision,
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    hideApproval: vi.fn(),
    removeApproval: vi.fn(),
    updateStatus: vi.fn(),
    updateProgressStep: vi.fn(),
    setError: vi.fn(),
    getActiveFollowUpId: vi.fn(),
  },
}));

let ApprovalOverlay: typeof import('./ApprovalOverlay').default;
let ApprovalSetOverlay: typeof import('./ApprovalSetOverlay').default;

beforeAll(async () => {
  ApprovalOverlay = (await import('./ApprovalOverlay')).default;
  ApprovalSetOverlay = (await import('./ApprovalSetOverlay')).default;
});

afterEach(() => {
  submitApprovalDecision.mockReset();
});

const shellApproval: ExecutionApprovalRequest = {
  approval_id: 'approval-shell',
  agent_task_id: 'task-1',
  command: 'ls -la',
  reason: 'Command not in whitelist',
  risk_level: 'low',
  execution_type: 'shell',
};

const providerApproval: ExecutionApprovalRequest = {
  approval_id: 'permission-1',
  agent_task_id: 'task-1',
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

const providerApprovalWithoutAllow: ExecutionApprovalRequest = {
  ...providerApproval,
  provider_permission: {
    interaction_id: 'permission-1',
    provider_run_id: 'run-1',
    agent_task_id: 'task-1',
    subject: { type: 'command', command: 'rm -rf /tmp/scratch', cwd: '/tmp' },
    allow_option_id: null,
    reject_option_id: 'reject-once',
  },
};

describe('ApprovalOverlay provider permission presentation', () => {
  it('renders provider permission title, badge, and no remember checkbox', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={providerApproval} rememberChoice={false} />
    );

    expect(markup).toContain('Provider Permission Request');
    expect(markup).toContain('Provider');
    expect(markup).toContain('rm -rf /tmp/scratch');
    expect(markup).not.toContain('Remember this choice');
  });

  it('disables Approve when no allow option was offered', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay
        agentTaskId="task-1"
        approval={providerApprovalWithoutAllow}
        rememberChoice={false}
      />
    );

    expect(markup).toContain('action-btn success');
    expect(markup).toContain('disabled=""');
  });
});

describe('ApprovalOverlay existing approval types', () => {
  it('keeps shell approval presentation unchanged', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={shellApproval} rememberChoice={false} />
    );

    expect(markup).toContain('Command Approval Required');
    expect(markup).toContain('Remember this choice');
    expect(markup).not.toContain('Provider Permission Request');
  });

  it('submits the approval owner turn instead of the root display task', async () => {
    submitApprovalDecision.mockResolvedValue({ success: true, message: 'approved' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ApprovalOverlay
          agentTaskId="root-task"
          approval={{ ...shellApproval, agent_task_id: 'child-turn' }}
          rememberChoice={false}
        />,
      );
    });

    const approveButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Approve');
    await act(async () => {
      approveButton?.click();
    });

    expect(submitApprovalDecision).toHaveBeenCalledWith(expect.objectContaining({
      approval_id: 'approval-shell',
      agent_task_id: 'child-turn',
    }));
    act(() => root.unmount());
  });

  it('renders every approval in a simultaneous approval set', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[
          shellApproval,
          { ...shellApproval, approval_id: 'approval-shell-2', command: 'mdfind Calls_Meetings' },
        ]}
        rememberChoice={false}
      />,
    );

    expect(markup).toContain('2 Command Approvals Required');
    expect(markup).toContain('ls -la');
    expect(markup).toContain('mdfind Calls_Meetings');
  });
});

describe('ApprovalSetOverlay single-approval rendering (regression)', () => {
  it('renders exactly one "Command Approval Required" occurrence and no aggregate wrapper card', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[shellApproval]}
        rememberChoice={false}
      />,
    );

    const titleOccurrences = markup.split('Command Approval Required').length - 1;
    expect(titleOccurrences).toBe(1);
    // The single-approval path renders ApprovalOverlay directly (embedded
    // is left at its default false), so the inert approval-set-card
    // wrapper class -- only meaningful for the multi-approval stack --
    // should never appear, and there should be exactly one overlay-backdrop
    // (not one from ApprovalSetOverlay nested around another from
    // ApprovalOverlay).
    expect(markup).not.toContain('approval-set-card');
    expect(markup.match(/overlay-backdrop/g)?.length).toBe(1);
  });

  it('does not repeat the shell-command title for each embedded item in a simultaneous approval set', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[
          shellApproval,
          { ...shellApproval, approval_id: 'approval-shell-2', command: 'mdfind Calls_Meetings' },
        ]}
        rememberChoice={false}
      />,
    );

    expect(markup).toContain('2 Command Approvals Required');
    // The literal singular heading would only appear if an embedded item
    // redundantly repeated it; the aggregate header uses the plural form.
    expect(markup).not.toContain('Command Approval Required');
    expect(markup).toContain('approval-set-card');
  });
});
