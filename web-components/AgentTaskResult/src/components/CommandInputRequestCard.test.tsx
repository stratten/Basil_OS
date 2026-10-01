// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ExecutionApprovalRequest } from '../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const submitCommandInput = vi.fn();
const removeApproval = vi.fn();
const updateProgressStep = vi.fn();

vi.mock('../services/api', () => ({
  submitCommandInput,
  submitApprovalDecision: vi.fn(),
  submitBrowserSensitiveFillApproval: vi.fn(),
  submitProviderPermissionDecision: vi.fn(),
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    removeApproval,
    updateProgressStep,
    hideApproval: vi.fn(),
    updateStatus: vi.fn(),
    setError: vi.fn(),
    getActiveFollowUpId: vi.fn(),
  },
}));

let CommandInputRequestCard: typeof import('./CommandInputRequestCard').default;
let ApprovalSetOverlay: typeof import('./ApprovalSetOverlay').default;

beforeAll(async () => {
  CommandInputRequestCard = (await import('./CommandInputRequestCard')).default;
  ApprovalSetOverlay = (await import('./ApprovalSetOverlay')).default;
});

afterEach(() => {
  submitCommandInput.mockReset();
  removeApproval.mockReset();
  updateProgressStep.mockReset();
});

const secretRequest: ExecutionApprovalRequest = {
  approval_id: 'command-input-1',
  agent_task_id: 'task-1',
  command: 'sudo softwareupdate --list',
  reason: 'The command is asking for input: Password:',
  risk_level: 'medium',
  execution_type: 'command_input',
  command_input: {
    request_id: 'command-input-1',
    agent_task_id: 'task-1',
    prompt: 'Password:',
    secret: true,
    command: 'sudo softwareupdate --list',
    created_at: 1_800_000_000,
    expires_at: 1_800_000_300,
  },
};

const confirmRequest: ExecutionApprovalRequest = {
  ...secretRequest,
  approval_id: 'command-input-2',
  command: 'brew upgrade',
  risk_level: 'low',
  command_input: {
    request_id: 'command-input-2',
    agent_task_id: 'task-1',
    prompt: 'Continue? [y/N]',
    secret: false,
  },
};

function mount(approval: ExecutionApprovalRequest): { container: HTMLDivElement; root: Root } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<CommandInputRequestCard agentTaskId="root-task" approval={approval} />);
  });
  return { container, root };
}

async function typeInto(input: HTMLInputElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  await act(async () => {
    setter?.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submitForm(container: HTMLElement) {
  const form = container.querySelector('form');
  await act(async () => {
    form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
}

describe('CommandInputRequestCard', () => {
  it('masks secret prompts and shows the command and prompt', () => {
    const markup = renderToStaticMarkup(
      <CommandInputRequestCard agentTaskId="task-1" approval={secretRequest} />
    );
    expect(markup).toContain('Command Needs Your Input');
    expect(markup).toContain('sudo softwareupdate --list');
    expect(markup).toContain('Password:');
    expect(markup).toContain('type="password"');
    expect(markup).toContain('Basil does not save or log it');
  });

  it('uses a plain text field for non-secret prompts', () => {
    const markup = renderToStaticMarkup(
      <CommandInputRequestCard agentTaskId="task-1" approval={confirmRequest} />
    );
    expect(markup).toContain('type="text"');
    expect(markup).not.toContain('Basil does not save or log it');
  });

  it('sends the typed answer to the owning task and removes the card', async () => {
    submitCommandInput.mockResolvedValue({ success: true, message: 'Input sent' });
    const { container, root } = mount(confirmRequest);
    await typeInto(container.querySelector('input') as HTMLInputElement, 'y');
    await submitForm(container);

    expect(submitCommandInput).toHaveBeenCalledWith({
      request_id: 'command-input-2',
      agent_task_id: 'task-1',
      action: 'answer',
      value: 'y',
    });
    expect(removeApproval).toHaveBeenCalledWith('root-task', 'command-input-2');
    act(() => root.unmount());
  });

  it('stops the command without sending a value', async () => {
    submitCommandInput.mockResolvedValue({ success: true, message: 'Input request canceled' });
    const { container, root } = mount(secretRequest);
    const stopButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Stop Command');
    await act(async () => {
      stopButton?.click();
    });

    expect(submitCommandInput).toHaveBeenCalledWith({
      request_id: 'command-input-1',
      agent_task_id: 'task-1',
      action: 'cancel',
      value: undefined,
    });
    expect(removeApproval).toHaveBeenCalledWith('root-task', 'command-input-1');
    act(() => root.unmount());
  });

  it('removes a stale card when the backend says the request is gone', async () => {
    submitCommandInput.mockRejectedValue(new Error('command input request is not pending (404)'));
    const { container, root } = mount(confirmRequest);
    await submitForm(container);

    expect(removeApproval).toHaveBeenCalledWith('root-task', 'command-input-2');
    expect(updateProgressStep).toHaveBeenCalledWith(
      'root-task',
      'The command is no longer waiting for input.',
      true,
      false,
    );
    act(() => root.unmount());
  });

  it('keeps the card and shows the error for other failures', async () => {
    submitCommandInput.mockRejectedValue(new Error('Input must be a single line without control characters (422)'));
    const { container, root } = mount(confirmRequest);
    await submitForm(container);

    expect(removeApproval).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('single line');
    act(() => root.unmount());
  });
});

describe('ApprovalSetOverlay command input routing', () => {
  it('renders a lone command input with the input card, not the approval overlay', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay agentTaskId="task-1" approvals={[confirmRequest]} rememberChoice={false} />
    );
    expect(markup).toContain('Command Needs Your Input');
    expect(markup).not.toContain('Command Approval Required');
    expect(markup).not.toContain('Remember this choice');
  });

  it('uses a neutral aggregate title when approvals and inputs are mixed', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[
          confirmRequest,
          {
            approval_id: 'approval-shell',
            agent_task_id: 'task-1',
            command: 'ls -la',
            reason: 'Command not in whitelist',
            risk_level: 'low',
            execution_type: 'shell',
          },
        ]}
        rememberChoice={false}
      />
    );
    expect(markup).toContain('2 Requests Need Your Response');
    expect(markup).toContain('Command Needs Your Input');
    expect(markup).toContain('ls -la');
  });
});
