// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../types';

const mocks = vi.hoisted(() => ({
  continueSession: vi.fn(),
  addClarification: vi.fn(),
  respondToProviderInteraction: vi.fn(),
  beginCheckpointAnswer: vi.fn(),
  settleAnsweredCheckpoint: vi.fn(),
  reopenCheckpointAfterFailedAnswer: vi.fn(),
  updateProgressStep: vi.fn(),
  showCheckpoint: vi.fn(),
  updateStatus: vi.fn(),
  hideCheckpoint: vi.fn(),
  dismissCheckpoint: vi.fn(),
}));

vi.mock('../services/api', () => ({
  continueSession: mocks.continueSession,
  addClarification: mocks.addClarification,
  respondToProviderInteraction: mocks.respondToProviderInteraction,
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    beginCheckpointAnswer: mocks.beginCheckpointAnswer,
    settleAnsweredCheckpoint: mocks.settleAnsweredCheckpoint,
    reopenCheckpointAfterFailedAnswer: mocks.reopenCheckpointAfterFailedAnswer,
    updateProgressStep: mocks.updateProgressStep,
    showCheckpoint: mocks.showCheckpoint,
    updateStatus: mocks.updateStatus,
    hideCheckpoint: mocks.hideCheckpoint,
    dismissCheckpoint: mocks.dismissCheckpoint,
  },
}));

let CheckpointFlow: typeof import('./CheckpointFlow').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  CheckpointFlow = (await import('./CheckpointFlow')).default;
});

beforeEach(() => {
  Object.values(mocks).forEach(mock => mock.mockReset());
  mocks.continueSession.mockResolvedValue(undefined);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const emailBody = 'To: mariam@example.com\n\nSubject: Re: Storage limits\n\nHi Mariam, the purge is ready.';

const approval: CheckpointData = {
  checkpoint_id: 'confirm-1',
  prompt: 'Send this reply to Mariam now?',
  input_type: 'confirmation',
  details_markdown: emailBody,
};

const question: CheckpointData = {
  checkpoint_id: 'text-1',
  prompt: 'Any changes to the draft before I save it?',
  input_type: 'data',
  details_markdown: emailBody,
};

function render(checkpoint: CheckpointData) {
  act(() => {
    root.render(<CheckpointFlow agentTaskId="task-1" checkpoint={checkpoint} mode="inline" />);
  });
}

function disclosure(): HTMLDetailsElement | null {
  return container.querySelector<HTMLDetailsElement>('details.checkpoint-details');
}

function summary(): HTMLElement {
  const element = container.querySelector<HTMLElement>('.checkpoint-details-summary');
  if (!element) throw new Error('Details summary missing');
  return element;
}

describe('CheckpointFlow details disclosure', () => {
  it('shows the content open for an approval so the user sees what they are approving', () => {
    render(approval);
    expect(disclosure()?.open).toBe(true);
    expect(summary().textContent).toBe('Hide details');
    expect(disclosure()?.textContent).toContain('mariam@example.com');
    expect(disclosure()?.textContent).toContain('Hi Mariam, the purge is ready.');
  });

  it('keeps the content one click away for other questions', () => {
    render(question);
    expect(disclosure()?.open).toBe(false);
    expect(summary().textContent).toBe('Show details');
  });

  it('follows the native toggle so the label matches the state', () => {
    render(question);
    const element = disclosure();
    if (!element) throw new Error('Disclosure missing');
    act(() => {
      element.open = true;
      element.dispatchEvent(new Event('toggle'));
    });
    expect(summary().textContent).toBe('Hide details');
    act(() => {
      element.open = false;
      element.dispatchEvent(new Event('toggle'));
    });
    expect(summary().textContent).toBe('Show details');
  });

  it('renders nothing extra when there are no details, and keeps the approval buttons', () => {
    render({ ...approval, details_markdown: undefined });
    expect(disclosure()).toBeNull();
    expect(container.textContent).toContain('Send this reply to Mariam now?');
    const buttons = Array.from(container.querySelectorAll('button')).map(button => button.textContent);
    expect(buttons).toContain('Yes');
    expect(buttons).toContain('No');
  });

  it('keeps the answer controls present alongside long details', () => {
    render({ ...approval, details_markdown: `${'Long paragraph of the message body. '.repeat(400)}` });
    expect(disclosure()?.open).toBe(true);
    const buttons = Array.from(container.querySelectorAll('button')).map(button => button.textContent);
    expect(buttons).toContain('Yes');
    expect(buttons).toContain('Continue');
  });
});
