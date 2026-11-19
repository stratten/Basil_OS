// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../../types';
import { resetComposerDrafts } from '../../store/composerDraftStore';
import { resetFollowUpComposerViews } from '../../store/followUpComposerViewStore';

const mocks = vi.hoisted(() => ({
  answerQuestionWithNote: vi.fn(),
  pauseSession: vi.fn(),
  sendRunMessage: vi.fn(),
}));

vi.mock('../interaction/answerWithNote', () => ({
  answerQuestionWithNote: mocks.answerQuestionWithNote,
}));

vi.mock('../../services/api', () => ({
  pauseSession: mocks.pauseSession,
  resumeSession: vi.fn(),
  sendRunMessage: mocks.sendRunMessage,
  getReasoningModels: vi.fn(),
}));

vi.mock('../../services/bridge', () => ({
  pickFiles: vi.fn(),
  registerFilesPickedHandler: () => () => undefined,
}));

let RunControlComposer: typeof import('./RunControlComposer').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const question: CheckpointData = { checkpoint_id: 'cp-1', prompt: 'How should I proceed?', input_type: 'data' };

beforeAll(async () => {
  RunControlComposer = (await import('./RunControlComposer')).default;
});

beforeEach(() => {
  [mocks.answerQuestionWithNote, mocks.pauseSession, mocks.sendRunMessage].forEach(mock => mock.mockReset());
  mocks.answerQuestionWithNote.mockResolvedValue(undefined);
  resetComposerDrafts();
  resetFollowUpComposerViews();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function renderAwaiting(checkpoint: CheckpointData | null = question) {
  act(() => {
    root.render(
      <RunControlComposer
        turnTaskId="turn-1"
        rootTaskId="root-1"
        mode="awaiting"
        awaitingCheckpoint={checkpoint ?? undefined}
        deliveredNoteIds={new Set()}
      />,
    );
  });
  const element = editor();
  if (!Object.getOwnPropertyDescriptor(element, 'innerText')) {
    Object.defineProperty(element, 'innerText', { configurable: true, get: () => element.textContent ?? '' });
  }
}

function editor(): HTMLDivElement {
  const element = container.querySelector<HTMLDivElement>('[role="textbox"]');
  if (!element) throw new Error('Expected the answer box.');
  return element;
}

function type(value: string) {
  act(() => {
    editor().textContent = value;
    editor().dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function pressCommandReturn() {
  await act(async () => {
    editor().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true, cancelable: true }));
  });
}

describe('RunControlComposer awaiting a question', () => {
  it('offers an answer box with no Pause and no fold control, and says what it is waiting for', () => {
    renderAwaiting();

    expect(editor().getAttribute('aria-label')).toBe('Answer to the question Basil asked');
    expect(container.querySelector('button[aria-label="Pause"]')).toBeNull();
    expect(container.querySelector('button[aria-label="Collapse the note box"]')).toBeNull();
    expect(container.textContent).toContain('Waiting for your answer');
  });

  it('sends the typed text as the answer to the open question, never as a run note', async () => {
    renderAwaiting();
    type('Use the second draft');

    await pressCommandReturn();

    expect(mocks.answerQuestionWithNote).toHaveBeenCalledWith('turn-1', question, 'Use the second draft');
    expect(mocks.sendRunMessage).not.toHaveBeenCalled();
    expect(mocks.pauseSession).not.toHaveBeenCalled();
  });

  it('shows the reason and keeps the text when the answer could not be delivered', async () => {
    mocks.answerQuestionWithNote.mockRejectedValue(new Error('Basil is offline (503)'));
    renderAwaiting();
    type('Use the second draft');

    await pressCommandReturn();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Basil is offline');
    expect(editor().textContent).toBe('Use the second draft');
  });

  it('refuses to send when no question is open', async () => {
    renderAwaiting(null);
    type('Anything');

    await pressCommandReturn();

    expect(mocks.answerQuestionWithNote).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Basil has no question open to answer.');
  });
});
