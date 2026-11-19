// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../../types';

const mocks = vi.hoisted(() => ({
  hydrateAgentFromBackend: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  continueSession: vi.fn(),
  addClarification: vi.fn(),
  respondToProviderInteraction: vi.fn(),
}));

vi.mock('../../store/agentStore', () => ({
  agentStore: {
    beginCheckpointAnswer: vi.fn(),
    settleAnsweredCheckpoint: vi.fn(),
    reopenCheckpointAfterFailedAnswer: vi.fn(),
    updateProgressStep: vi.fn(),
    showCheckpoint: vi.fn(),
    updateStatus: vi.fn(),
    hideCheckpoint: vi.fn(),
    dismissCheckpoint: vi.fn(),
  },
}));

vi.mock('../../app/agents/agentHydration', () => ({
  hydrateAgentFromBackend: mocks.hydrateAgentFromBackend,
}));

let CheckpointFlow: typeof import('./CheckpointFlow').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  CheckpointFlow = (await import('./CheckpointFlow')).default;
});

beforeEach(() => {
  mocks.hydrateAgentFromBackend.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const recoveryPrompt: CheckpointData = {
  checkpoint_id: 'recovered-waiting-turn',
  session_agent_task_id: 'waiting-turn',
  prompt: 'Approve this reply-all to Brian and Mariam, or tell me what to change?',
  input_type: 'data',
  metadata: { source: 'checkpoint_recovery' },
};

const realApproval: CheckpointData = {
  checkpoint_id: 'approve-reply',
  session_agent_task_id: 'waiting-turn',
  prompt: 'Approve this reply-all to Brian and Mariam, or tell me what to change?',
  input_type: 'confirmation',
  details_markdown: '**To:** brian@example.com',
};

function render(checkpoint: CheckpointData): void {
  act(() => {
    root.render(<CheckpointFlow agentTaskId="chain-root" checkpoint={checkpoint} mode="overlay" />);
  });
}

const retryButton = () => container.querySelector<HTMLButtonElement>('.checkpoint-recovery-notice__retry');

describe('CheckpointFlow recovery prompt', () => {
  it('tells the reader the question could not be loaded and offers to load it again', () => {
    render(recoveryPrompt);

    const notice = container.querySelector('.checkpoint-recovery-notice');
    expect(notice?.getAttribute('role')).toBe('alert');
    expect(notice?.textContent).toContain('The details of this question could not be loaded');
    expect(notice?.textContent).toContain('the content you are being asked to approve');
    expect(retryButton()?.textContent).toBe('Try again');
    expect(retryButton()?.disabled).toBe(false);
  });

  it('shows no notice for a question that was read in full', () => {
    render(realApproval);

    expect(container.querySelector('.checkpoint-recovery-notice')).toBeNull();
  });

  it('reads the waiting question again for the same task, and disables the button while it does', async () => {
    let finish: () => void = () => {};
    mocks.hydrateAgentFromBackend.mockReturnValue(new Promise<void>(resolve => { finish = resolve; }));
    render(recoveryPrompt);

    await act(async () => {
      retryButton()?.click();
    });
    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledWith('chain-root');
    expect(retryButton()?.textContent).toBe('Loading...');
    expect(retryButton()?.disabled).toBe(true);

    await act(async () => {
      finish();
    });
  });

  it('says so when the question still cannot be loaded, and lets the reader try again', async () => {
    mocks.hydrateAgentFromBackend.mockResolvedValue('hydrated');
    render(recoveryPrompt);

    await act(async () => {
      retryButton()?.click();
    });

    expect(container.querySelector('.checkpoint-recovery-notice')?.textContent).toContain('still could not be loaded');
    expect(retryButton()?.textContent).toBe('Try again');
    expect(retryButton()?.disabled).toBe(false);
  });

  it('starts fresh when the real question replaces the recovery prompt, with its details open for an approval', () => {
    render(recoveryPrompt);
    expect(container.querySelector('details')).toBeNull();

    render(realApproval);

    expect(container.querySelector('.checkpoint-recovery-notice')).toBeNull();
    expect(container.querySelector('details')?.hasAttribute('open')).toBe(true);
    expect(container.textContent).toContain('brian@example.com');
  });
});
