// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TextFollowUp from './TextFollowUp';
import { SuggestedFollowUps } from './SuggestedFollowUps';
import { resetFollowUpComposerViews } from '../store/followUpComposerViewStore';
import { resetFollowUpPrefillRequests } from '../store/followUpPrefillStore';
import { resetComposerDrafts } from '../store/composerDraftStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: 'm' }),
  processAgentTask: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../services/api', () => ({
  getReasoningModels: mocks.getReasoningModels,
  processAgentTask: mocks.processAgentTask,
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    getAgent: vi.fn().mockReturnValue(undefined),
    getCurrentTurnTaskId: vi.fn((rootTaskId: string) => rootTaskId),
    beginFollowUpTurn: vi.fn(),
    updateAgentTaskText: vi.fn(),
    updateAgentDisplayPromptMarkdown: vi.fn(),
    setError: vi.fn(),
    setSelectedModelId: vi.fn(),
    updateOriginalModelId: vi.fn(),
    setReferencePaths: vi.fn(),
    setAgentTaskHistory: vi.fn(),
  },
}));

vi.mock('../services/bridge', () => ({
  registerFilesPickedHandler: () => () => {},
  pickFiles: vi.fn(),
}));

const SUGGESTIONS = ['Draft a reply', 'Archive the newsletters', 'Flag the invoices'];

let container: HTMLDivElement;
let root: Root;

function chips(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button.suggested-follow-up-chip'));
}

function editor(): HTMLDivElement {
  return container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
}

// jsdom has no innerText, so give the editor the line-per-block text a browser would report.
function emulateInnerText(element: HTMLElement) {
  Object.defineProperty(element, 'innerText', {
    configurable: true,
    get: () => Array.from(element.childNodes).map(node => node.textContent ?? '').join('\n'),
  });
}

async function click(button: HTMLButtonElement) {
  await act(async () => { button.click(); });
}

beforeEach(async () => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <>
        <SuggestedFollowUps taskKey="task-1" suggestions={SUGGESTIONS} />
        <TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} alwaysVisible />
      </>,
    );
  });
  emulateInnerText(editor());
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetComposerDrafts();
  resetFollowUpComposerViews();
  resetFollowUpPrefillRequests();
  vi.clearAllMocks();
});

describe('suggested follow-ups: picking several before sending', () => {
  it('combines every picked chip in the box, one per line, and sends nothing', async () => {
    await click(chips()[0]);
    await click(chips()[2]);

    expect(Array.from(editor().childNodes).map(node => node.textContent)).toEqual(['Draft a reply', 'Flag the invoices']);
    expect(chips().map(chip => chip.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'true']);
    expect(mocks.processAgentTask).not.toHaveBeenCalled();
  });

  it('unpicks a chip when it is clicked again, keeping the others', async () => {
    await click(chips()[0]);
    await click(chips()[1]);
    await click(chips()[0]);

    expect(Array.from(editor().childNodes).map(node => node.textContent)).toEqual(['Archive the newsletters']);
    expect(chips().map(chip => chip.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);
  });

  it('keeps what the reader typed when chips are picked and unpicked', async () => {
    await act(async () => {
      editor().textContent = 'Please be brief';
      editor().dispatchEvent(new Event('input', { bubbles: true }));
    });
    await click(chips()[0]);
    await click(chips()[0]);

    expect(editor().textContent).toBe('Please be brief');
  });

  it('shows a chip as unpicked once its line is deleted by hand, and picks it again on the next click', async () => {
    await click(chips()[0]);
    expect(chips()[0].getAttribute('aria-pressed')).toBe('true');

    await act(async () => {
      editor().innerHTML = '';
      editor().dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(chips()[0].getAttribute('aria-pressed')).toBe('false');

    await click(chips()[0]);
    expect(editor().textContent).toBe('Draft a reply');
  });

  it('clears every picked state once the draft is gone', async () => {
    await click(chips()[0]);
    await click(chips()[1]);
    await act(async () => {
      editor().innerHTML = '';
      editor().dispatchEvent(new Event('input', { bubbles: true }));
    });

    expect(chips().every(chip => chip.getAttribute('aria-pressed') === 'false')).toBe(true);
  });
});
