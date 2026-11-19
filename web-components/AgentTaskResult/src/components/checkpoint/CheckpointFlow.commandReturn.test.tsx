// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../../types';

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

vi.mock('../../services/api', () => ({
  continueSession: mocks.continueSession,
  addClarification: mocks.addClarification,
  respondToProviderInteraction: mocks.respondToProviderInteraction,
}));

vi.mock('../../store/agentStore', () => ({
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

const question: CheckpointData = {
  checkpoint_id: 'text-1',
  prompt: 'Where is the venue?',
  input_type: 'data',
};

const approval: CheckpointData = {
  checkpoint_id: 'confirm-1',
  prompt: 'Send this reply now?',
  input_type: 'confirmation',
};

function render(checkpoint: CheckpointData) {
  act(() => {
    root.render(<CheckpointFlow agentTaskId="task-1" checkpoint={checkpoint} mode="inline" />);
  });
}

function field(selector: string): HTMLTextAreaElement {
  const element = container.querySelector<HTMLTextAreaElement>(selector);
  if (!element) throw new Error(`Missing ${selector}`);
  return element;
}

function type(element: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => {
    setter?.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function press(element: HTMLElement, init: KeyboardEventInit) {
  const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...init });
  await act(async () => {
    element.dispatchEvent(event);
  });
  return event;
}

describe('CheckpointFlow Command-Return', () => {
  it('sends the typed answer, the same as pressing Continue', async () => {
    render(question);
    const input = field('textarea.text-followup-input');
    type(input, 'New York');

    const event = await press(input, { metaKey: true });

    expect(event.defaultPrevented).toBe(true);
    expect(mocks.continueSession).toHaveBeenCalledTimes(1);
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'New York');
  });

  it('accepts Control-Return too', async () => {
    render(question);
    const input = field('textarea.text-followup-input');
    type(input, 'New York');

    await press(input, { ctrlKey: true });

    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'New York');
  });

  it('sends a note typed in the Other box of an approval', async () => {
    render(approval);
    const input = field('#checkpoint-clarification-input');
    type(input, 'Change the subject first');

    await press(input, { metaKey: true });

    expect(mocks.continueSession).toHaveBeenCalledTimes(1);
    expect(mocks.continueSession.mock.calls[0][1]).toContain('Change the subject first');
  });

  it('sends nothing when the field is empty, and does not insert a line break', async () => {
    render(question);
    const input = field('textarea.text-followup-input');

    const event = await press(input, { metaKey: true });

    expect(event.defaultPrevented).toBe(true);
    expect(mocks.continueSession).not.toHaveBeenCalled();
  });

  it('leaves plain Return alone so it still adds a line', async () => {
    render(question);
    const input = field('textarea.text-followup-input');
    type(input, 'First line');

    const event = await press(input, {});

    expect(event.defaultPrevented).toBe(false);
    expect(mocks.continueSession).not.toHaveBeenCalled();
  });

  it('does not send twice while the answer is already being delivered', async () => {
    let finishSend: () => void = () => undefined;
    mocks.continueSession.mockReturnValue(new Promise<void>(resolve => { finishSend = resolve; }));
    render(question);
    const input = field('textarea.text-followup-input');
    type(input, 'New York');

    await press(input, { metaKey: true });
    await press(input, { metaKey: true });

    expect(mocks.continueSession).toHaveBeenCalledTimes(1);
    await act(async () => finishSend());
  });
});
