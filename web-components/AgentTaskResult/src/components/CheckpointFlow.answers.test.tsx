// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../types';

const mocks = vi.hoisted(() => ({
  continueSession: vi.fn(),
  addClarification: vi.fn(),
  respondToProviderInteraction: vi.fn(),
  markCheckpointResumeProcessing: vi.fn(),
  updateProgressStep: vi.fn(),
  showCheckpoint: vi.fn(),
  updateStatus: vi.fn(),
  hideCheckpoint: vi.fn(),
}));

vi.mock('../services/api', () => ({
  continueSession: mocks.continueSession,
  addClarification: mocks.addClarification,
  respondToProviderInteraction: mocks.respondToProviderInteraction,
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    markCheckpointResumeProcessing: mocks.markCheckpointResumeProcessing,
    updateProgressStep: mocks.updateProgressStep,
    showCheckpoint: mocks.showCheckpoint,
    updateStatus: mocks.updateStatus,
    hideCheckpoint: mocks.hideCheckpoint,
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

const reportOptions = [
  { id: 'sales', label: 'Sales', value: 'sales' },
  { id: 'support', label: 'Support', value: 'support' },
  { id: 'ops', label: 'Operations', value: 'ops' },
];

const singleChoice: CheckpointData = {
  checkpoint_id: 'choice-1',
  prompt: 'Which report should Basil prepare?',
  input_type: 'choice',
  options: reportOptions,
};

const multiChoice: CheckpointData = { ...singleChoice, checkpoint_id: 'choice-2', allow_multiple: true };

const confirmation: CheckpointData = {
  checkpoint_id: 'confirm-1',
  prompt: 'Send the draft?',
  input_type: 'confirmation',
};

const targetAuthorization: CheckpointData = {
  checkpoint_id: 'auth-1',
  prompt: 'Which provider and authorized workspace should Basil use for this delegation?',
  input_type: 'choice',
  allow_multiple: true,
  options: [
    { id: 'target-option-1', label: 'Fixture Provider — Workspace grant-a', value: 'target-choice:token-1' },
  ],
  metadata: {
    source: 'provider_target_authorization',
    authorization_id: 'auth-1',
    cancel_value: 'target-cancel:token-1',
  },
};

function render(checkpoint: CheckpointData) {
  act(() => {
    root.render(<CheckpointFlow agentTaskId="task-1" checkpoint={checkpoint} mode="inline" />);
  });
}

function card(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('.checkpoint-choice-card'))
    .find(button => button.querySelector('.checkpoint-choice-title')?.textContent === label);
  if (!match) throw new Error(`No card labeled ${label}`);
  return match;
}

function actionButton(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('.checkpoint-submit-actions button'))
    .find(button => button.textContent === label);
  if (!match) throw new Error(`No action button labeled ${label}`);
  return match;
}

function otherInput(): HTMLTextAreaElement {
  const input = container.querySelector<HTMLTextAreaElement>('#checkpoint-clarification-input');
  if (!input) throw new Error('Other field missing');
  return input;
}

function typeInto(element: HTMLTextAreaElement | HTMLInputElement, value: string) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click();
  });
}

describe('CheckpointFlow choice answers', () => {
  it('sends a single pick as the bare option value', async () => {
    render(singleChoice);
    expect(container.querySelectorAll('.checkpoint-choice-indicator--radio')).toHaveLength(3);
    expect(container.textContent).not.toContain('Select all that apply.');
    await click(card('Support'));
    await click(card('Sales'));
    expect(card('Sales').getAttribute('aria-pressed')).toBe('true');
    expect(card('Support').getAttribute('aria-pressed')).toBe('false');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'sales');
  });

  it('toggles several options and labels them in option order', async () => {
    render(multiChoice);
    expect(container.textContent).toContain('Select all that apply.');
    expect(container.querySelectorAll('.checkpoint-choice-indicator--checkbox')).toHaveLength(3);
    await click(card('Operations'));
    await click(card('Support'));
    await click(card('Sales'));
    await click(card('Support'));
    expect(card('Support').getAttribute('aria-pressed')).toBe('false');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Selected: sales; ops');
  });

  it('keeps Other text alongside a selection', async () => {
    render(multiChoice);
    await click(card('Sales'));
    typeInto(otherInput(), '  Include last quarter too.  ');
    expect(card('Sales').getAttribute('aria-pressed')).toBe('true');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Selected: sales\nOther: Include last quarter too.');
  });

  it('enables Continue for Other text alone and labels it', async () => {
    render(singleChoice);
    expect(container.textContent).toContain('Other');
    expect(actionButton('Continue').disabled).toBe(true);
    typeInto(otherInput(), 'Marketing instead');
    expect(actionButton('Continue').disabled).toBe(false);
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Other: Marketing instead');
  });
});

describe('CheckpointFlow provider target authorization answers', () => {
  it('ignores multi-select and sends typed text bare after clearing the card', async () => {
    render(targetAuthorization);
    expect(container.querySelectorAll('.checkpoint-choice-indicator--checkbox')).toHaveLength(0);
    expect(container.querySelectorAll('.checkpoint-choice-indicator--radio')).toHaveLength(1);
    expect(container.textContent).not.toContain('Select all that apply.');
    expect(container.textContent).toContain('Different target or clarification');
    await click(card('Fixture Provider — Workspace grant-a'));
    typeInto(otherInput(), 'Use the staging workspace');
    expect(card('Fixture Provider — Workspace grant-a').getAttribute('aria-pressed')).toBe('false');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Use the staging workspace');
  });

  it('clears typed text when a card is chosen and sends the bare token', async () => {
    render(targetAuthorization);
    typeInto(otherInput(), 'Something else');
    await click(card('Fixture Provider — Workspace grant-a'));
    expect(otherInput().value).toBe('');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'target-choice:token-1');
  });
});

describe('CheckpointFlow confirmation answers', () => {
  it('submits Yes immediately as the bare value', async () => {
    render(confirmation);
    expect(container.querySelectorAll('.checkpoint-choice-indicator')).toHaveLength(0);
    await click(card('Yes'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'yes');
  });

  it('labels a typed note sent with No', async () => {
    render(confirmation);
    typeInto(otherInput(), 'Wait until Friday');
    await click(card('No'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Selected: no\nOther: Wait until Friday');
  });

  it('requires Other text for Continue and sends it labeled', async () => {
    render(confirmation);
    expect(actionButton('Continue').disabled).toBe(true);
    typeInto(otherInput(), 'Only send the summary');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Other: Only send the summary');
  });

  it('Skip hides the prompt without answering', async () => {
    render(confirmation);
    await click(actionButton('Skip'));
    expect(mocks.hideCheckpoint).toHaveBeenCalledWith('task-1');
    expect(mocks.continueSession).not.toHaveBeenCalled();
  });
});

describe('CheckpointFlow data answers', () => {
  it('validates numeric prompts before enabling Continue', async () => {
    render({ checkpoint_id: 'numeric-1', prompt: 'How many emails?', input_type: 'data', value_kind: 'numeric' });
    const input = container.querySelector<HTMLInputElement>('.checkpoint-numeric-input');
    if (!input) throw new Error('Numeric input missing');
    expect(input.getAttribute('inputmode')).toBe('decimal');
    typeInto(input, 'about ten');
    expect(container.querySelector('#checkpoint-numeric-error')?.textContent).toContain('Enter a number');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(actionButton('Continue').disabled).toBe(true);
    typeInto(input, ' 1,250 ');
    expect(container.querySelector('#checkpoint-numeric-error')).toBeNull();
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', '1,250');
  });

  it('leaves plain text prompts unlabeled', async () => {
    render({ checkpoint_id: 'text-1', prompt: 'Any notes?', input_type: 'data' });
    expect(container.querySelector('.checkpoint-numeric-input')).toBeNull();
    const textarea = container.querySelector<HTMLTextAreaElement>('textarea.text-followup-input');
    if (!textarea) throw new Error('Text area missing');
    typeInto(textarea, 'Ship it');
    await click(actionButton('Continue'));
    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Ship it');
  });
});
