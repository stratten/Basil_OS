// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TextFollowUp from './TextFollowUp';
import { resetFollowUpComposerViews, setFollowUpComposerCollapsed } from '../store/followUpComposerViewStore';
import { requestFollowUpLineAdded, requestFollowUpPrefill, resetFollowUpPrefillRequests } from '../store/followUpPrefillStore';
import { discardComposerDraft, loadComposerDraft, resetComposerDrafts } from '../store/composerDraftStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  getReasoningModels: vi.fn().mockResolvedValue({
    models: [
      { id: 'local-qwen-3.5', name: 'Qwen 3.5', display_name: 'Qwen 3.5', provider: 'local', category: 'local', is_api_model: false },
      { id: 'gpt-5-mini', name: 'GPT-5 mini', display_name: 'GPT-5 mini', provider: 'openai', category: 'api', is_api_model: true },
    ],
    current_model: 'local-qwen-3.5',
  }),
  processAgentTask: vi.fn().mockResolvedValue(undefined),
  getAgent: vi.fn().mockReturnValue(undefined),
  getCurrentTurnTaskId: vi.fn((rootTaskId: string) => rootTaskId),
  beginFollowUpTurn: vi.fn(),
  updateAgentTaskText: vi.fn(),
  updateAgentDisplayPromptMarkdown: vi.fn(),
  setError: vi.fn(),
  setSelectedModelId: vi.fn(),
  updateOriginalModelId: vi.fn(),
  setReferencePaths: vi.fn(),
  setConnectionReferences: vi.fn(),
  setAgentTaskHistory: vi.fn(),
  filesPickedHandler: null as ((paths: string[]) => void) | null,
  registerFilesPickedHandler: vi.fn<(handler: (paths: string[]) => void) => () => void>(() => () => {}),
  pickFiles: vi.fn(),
}));

vi.mock('../services/api', () => ({
  getReasoningModels: mocks.getReasoningModels,
  processAgentTask: mocks.processAgentTask,
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    getAgent: mocks.getAgent,
    getCurrentTurnTaskId: mocks.getCurrentTurnTaskId,
    beginFollowUpTurn: mocks.beginFollowUpTurn,
    updateAgentTaskText: mocks.updateAgentTaskText,
    updateAgentDisplayPromptMarkdown: mocks.updateAgentDisplayPromptMarkdown,
    setError: mocks.setError,
    setSelectedModelId: mocks.setSelectedModelId,
    updateOriginalModelId: mocks.updateOriginalModelId,
    setReferencePaths: mocks.setReferencePaths,
    setConnectionReferences: mocks.setConnectionReferences,
    setAgentTaskHistory: mocks.setAgentTaskHistory,
  },
}));

vi.mock('../services/bridge', () => ({
  registerFilesPickedHandler: mocks.registerFilesPickedHandler,
  pickFiles: mocks.pickFiles,
}));

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(() => {
  resetComposerDrafts();
  resetFollowUpComposerViews();
  resetFollowUpPrefillRequests();
  act(() => root?.unmount());
  container?.remove();
  vi.clearAllMocks();
});

describe('TextFollowUp', () => {
  it('shows selected files compactly and publishes them before the follow-up completes', async () => {
    mocks.registerFilesPickedHandler.mockImplementation((handler) => {
      mocks.filesPickedHandler = handler;
      return () => { mocks.filesPickedHandler = null; };
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    const onCancel = vi.fn();

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={onCancel} />);
    });
    await act(async () => {
      mocks.filesPickedHandler?.(['/tmp/Karpathy Transcript.txt']);
    });

    expect(container.textContent).toContain('Attachments / References');
    expect(container.textContent).toContain('Karpathy Transcript.txt');
    expect(container.querySelector('[aria-label="Remove Karpathy Transcript.txt"]')).not.toBeNull();

    const editor = container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Please analyze this transcript.' });
    await act(async () => {
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });

    expect(mocks.setReferencePaths).toHaveBeenCalledWith('task-1', ['/tmp/Karpathy Transcript.txt']);
    // A follow-up is not given the earlier run's connection instructions, so its connection chips are cleared.
    expect(mocks.setConnectionReferences).toHaveBeenCalledWith('task-1', []);
    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
      reference_paths: ['/tmp/Karpathy Transcript.txt'],
    }));
  });

  it('highlights the composer region while a file drag is over it and clears the highlight on drop', async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} />);
    });

    const zone = container.querySelector('.text-followup') as HTMLElement;
    expect(zone.classList.contains('attachment-drop-zone')).toBe(true);
    expect(container.textContent).not.toContain('Drop files here');
    await act(async () => {
      zone.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).toContain('Drop files here');
    await act(async () => {
      zone.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).not.toContain('Drop files here');
  });

  it('uses the shared rich editor and submits its plaintext with Command-Return', async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    const onCancel = vi.fn();

    act(() => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={onCancel} />);
    });

    const editor = container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
    const sendButton = container.querySelector('button[aria-label="Send"]') as HTMLButtonElement;
    expect(editor).toBeTruthy();
    expect(sendButton.querySelector('svg')).toBeTruthy();
    expect(container.querySelector('[aria-label="Command-Return sends"]')?.textContent).toBe('⌘↩');

    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Follow up' });
    await act(async () => {
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });

    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
      agent_task: 'Follow up',
      previous_task_id: 'task-1',
    }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('defaults to a previously stored model preference instead of the system default', async () => {
    mocks.getAgent.mockReturnValue({ selectedModelId: 'gpt-5-mini' });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    const onCancel = vi.fn();

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={onCancel} />);
    });
    await act(async () => { await Promise.resolve(); });

    expect(container.querySelector('.rich-text-model-picker-trigger')?.textContent).toContain('GPT-5 mini');

    const editor = container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Follow up' });
    await act(async () => {
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });

    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
      model_id: 'gpt-5-mini',
    }));
  });

  it('defaults to the model the previous turn used when nothing was picked manually', async () => {
    mocks.getAgent.mockReturnValue({ originalModelId: 'gpt-5-mini' });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} />);
    });
    await act(async () => { await Promise.resolve(); });

    expect(container.querySelector('.rich-text-model-picker-trigger')?.textContent).toContain('GPT-5 mini');

    const editor = container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Follow up' });
    await act(async () => {
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });

    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({ model_id: 'gpt-5-mini' }));
    expect(mocks.updateOriginalModelId).toHaveBeenCalledWith('task-1', 'gpt-5-mini');
    mocks.getAgent.mockReturnValue(undefined);
  });

  it('carries the whole reopened chain into the new follow-up instead of only the latest turn', async () => {
    const historyItem = (id: string) => ({ id, agentTaskText: `prompt ${id}`, result: `answer ${id}`, files: [], reference_paths: [], timestamp: '2026-10-24T00:00:00.000Z' });
    const viewedChain = {
      agentTaskId: 'turn-5',
      rootTaskId: 'chain-root',
      currentTurnTaskId: 'turn-5',
      originalPrompt: 'prompt turn-5',
      result: 'answer turn-5',
      status: 'completed',
      structuredFiles: [],
      referencePaths: [],
      thinkingSegments: [],
      progressSteps: [],
      executionTimeline: [],
      stepDetails: [],
      agentTaskHistory: ['chain-root', 'turn-1', 'turn-2', 'turn-3', 'turn-4'].map(historyItem),
    };
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="turn-5" rootTaskId="chain-root" displaySource={viewedChain as never} onCancel={vi.fn()} />);
    });
    const editor = container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Next question' });
    await act(async () => {
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });

    const carried = mocks.setAgentTaskHistory.mock.calls[0];
    expect(carried[0]).toBe('chain-root');
    expect(carried[1].map((item: { id: string }) => item.id)).toEqual(['chain-root', 'turn-1', 'turn-2', 'turn-3', 'turn-4', 'turn-5']);
    expect(mocks.beginFollowUpTurn.mock.calls[0][2]).toEqual(expect.objectContaining({ id: 'turn-5', agentTaskText: 'prompt turn-5' }));
    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({ root_task_id: 'chain-root', previous_task_id: 'turn-5' }));
  });

  it('falls back to the default model when the previous turn model is no longer available', async () => {
    mocks.getAgent.mockReturnValue({ originalModelId: 'removed-model' });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} />);
    });
    await act(async () => { await Promise.resolve(); });

    expect(container.querySelector('.rich-text-model-picker-trigger')?.textContent).toContain('Qwen 3.5');
    mocks.getAgent.mockReturnValue(undefined);
  });
});

describe('TextFollowUp collapsing', () => {
  const mount = async (props: { alwaysVisible?: boolean } = {}) => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} {...props} />);
    });
  };
  const bar = () => container.querySelector('button.text-followup-bar') as HTMLButtonElement | null;
  const collapseButton = () => container.querySelector('button.text-followup-collapse-btn') as HTMLButtonElement | null;
  const region = () => container.querySelector('.basil-collapsible-region') as HTMLElement;
  const editor = () => container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;

  it('opens by default as just the text area, with no bar and the collapse arrow beside the attach icon', async () => {
    await mount();

    expect(bar()).toBeNull();
    expect(region().getAttribute('aria-hidden')).toBeNull();
    const toolbarEnd = container.querySelector('.rich-text-composer-toolbar-end') as HTMLElement;
    const buttons = Array.from(toolbarEnd.querySelectorAll('button')).map(button => button.getAttribute('aria-label'));
    expect(buttons).toEqual(['Attach files or folders', 'Collapse the follow-up box']);
    expect(collapseButton()!.getAttribute('aria-expanded')).toBe('true');
    expect(collapseButton()!.getAttribute('aria-controls')).toBe(region().id);
  });

  it('folds to the one-line bar and keeps the draft, shown as a preview on the bar', async () => {
    await mount();
    Object.defineProperty(editor(), 'innerText', { configurable: true, value: 'A half-written\n  question' });
    await act(async () => {
      editor().dispatchEvent(new Event('input', { bubbles: true }));
    });

    await act(async () => { collapseButton()!.click(); });

    expect(bar()!.getAttribute('aria-expanded')).toBe('false');
    expect(bar()!.getAttribute('aria-label')).toBe('Open the follow-up box');
    expect(bar()!.getAttribute('aria-controls')).toBe(region().id);
    expect(region().getAttribute('aria-hidden')).toBe('true');
    expect(region().hasAttribute('inert')).toBe(true);
    expect(container.querySelector('.text-followup-bar-draft')?.textContent).toBe('Draft: A half-written question');
    expect(editor()).not.toBeNull();
  });

  it('moves focus to the bar when the collapse arrow is used, since the arrow goes inert with the box', async () => {
    await mount();
    collapseButton()!.focus();
    await act(async () => { collapseButton()!.click(); });

    expect(document.activeElement).toBe(bar());
  });

  it('truncates a long draft preview', async () => {
    await mount();
    Object.defineProperty(editor(), 'innerText', { configurable: true, value: 'x'.repeat(200) });
    await act(async () => {
      editor().dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { collapseButton()!.click(); });

    expect(container.querySelector('.text-followup-bar-draft')?.textContent).toBe(`Draft: ${'x'.repeat(80)}...`);
  });

  it('focuses the editor and drops the bar when the reader opens it again', async () => {
    await mount();
    await act(async () => { collapseButton()!.click(); });
    (document.activeElement as HTMLElement | null)?.blur();
    await act(async () => { bar()!.click(); });

    expect(bar()).toBeNull();
    expect(region().getAttribute('aria-hidden')).toBeNull();
    expect(document.activeElement).toBe(editor());
  });

  it('stays folded when it merely reappears on a finished task', async () => {
    setFollowUpComposerCollapsed('task-1', true);
    await mount({ alwaysVisible: true });

    expect(bar()!.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).not.toBe(editor());
    expect(document.activeElement).not.toBe(bar());
  });

  it('opens a folded box and takes focus for an explicit follow-up', async () => {
    setFollowUpComposerCollapsed('task-1', true);
    await mount({ alwaysVisible: false });

    expect(bar()).toBeNull();
    expect(document.activeElement).toBe(editor());
  });

  it('remembers the fold per chain across a remount', async () => {
    await mount();
    await act(async () => { collapseButton()!.click(); });
    act(() => root.unmount());
    container.remove();

    await mount({ alwaysVisible: true });
    expect(bar()!.getAttribute('aria-expanded')).toBe('false');
  });
});

describe('TextFollowUp suggested follow-ups', () => {
  // jsdom has no innerText; the composer reads it on every input event, as a browser provides.
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'innerText', {
      configurable: true,
      get() { return (this as HTMLElement).textContent ?? ''; },
    });
  });
  afterEach(() => {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).innerText;
  });

  const mount = async (props: { alwaysVisible?: boolean } = {}) => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} {...props} />);
    });
  };
  const bar = () => container.querySelector('button.text-followup-bar') as HTMLButtonElement | null;
  const editor = () => container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;

  it('fills a folded box with a suggested follow-up as an editable draft without sending it', async () => {
    setFollowUpComposerCollapsed('task-1', true);
    await mount({ alwaysVisible: true });
    expect(bar()).not.toBeNull();

    await act(async () => { requestFollowUpPrefill('task-1', 'Draft a reply to the first email'); });

    expect(bar()).toBeNull();
    expect(editor().textContent).toBe('Draft a reply to the first email');
    expect(document.activeElement).toBe(editor());
    expect(mocks.processAgentTask).not.toHaveBeenCalled();
  });

  it('applies a suggestion requested before the box mounted, and only once', async () => {
    requestFollowUpPrefill('task-1', 'Summarize the second email');
    await mount({ alwaysVisible: true });

    expect(editor().textContent).toBe('Summarize the second email');

    await act(async () => { editor().textContent = 'Summarize the second email, shorter'; });
    await act(async () => { root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} alwaysVisible />); });
    expect(editor().textContent).toBe('Summarize the second email, shorter');
  });
});

describe('TextFollowUp keeps what was typed', () => {
  // jsdom has no innerText; the composer reads it on every input event, as a browser provides.
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'innerText', {
      configurable: true,
      get() { return (this as HTMLElement).textContent ?? ''; },
    });
  });
  afterEach(() => {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).innerText;
  });

  const mount = async (props: { agentTaskId?: string; rootTaskId?: string; onCancel?: () => void } = {}) => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<TextFollowUp agentTaskId={props.agentTaskId ?? 'task-1'} rootTaskId={props.rootTaskId} onCancel={props.onCancel ?? vi.fn()} alwaysVisible />);
    });
  };
  const remount = async (props: { agentTaskId?: string; rootTaskId?: string; onCancel?: () => void } = {}) => {
    act(() => root.unmount());
    container.remove();
    await mount(props);
  };
  const editor = () => container.querySelector('[role="textbox"][aria-label="Message"]') as HTMLDivElement;
  const type = async (html: string) => {
    editor().innerHTML = html;
    await act(async () => { editor().dispatchEvent(new Event('input', { bubbles: true })); });
  };

  it('puts the text back, formatting included, when the box is opened again', async () => {
    await mount();
    await type('Please <b>compare</b> the two');

    await remount();

    expect(editor().innerHTML).toBe('Please <b>compare</b> the two');
    expect(container.querySelector('button[aria-label="Send"]')?.hasAttribute('disabled')).toBe(false);
  });

  it('shows the restored text as the draft on a folded box', async () => {
    await mount();
    await type('A half-written question');
    setFollowUpComposerCollapsed('task-1', true);

    await remount();

    expect(container.querySelector('.text-followup-bar-draft')?.textContent).toBe('Draft: A half-written question');
  });

  it('keeps each task its own draft', async () => {
    await mount({ agentTaskId: 'task-a' });
    await type('for task A');
    await remount({ agentTaskId: 'task-b' });
    expect(editor().innerHTML).toBe('');
    await type('for task B');

    await remount({ agentTaskId: 'task-a' });
    expect(editor().innerHTML).toBe('for task A');
    await remount({ agentTaskId: 'task-b' });
    expect(editor().innerHTML).toBe('for task B');
  });

  it('restores attached files', async () => {
    mocks.registerFilesPickedHandler.mockImplementation((handler) => {
      mocks.filesPickedHandler = handler;
      return () => { mocks.filesPickedHandler = null; };
    });
    await mount();
    await act(async () => { mocks.filesPickedHandler?.(['/tmp/Plan.txt']); });

    await remount();

    expect(container.textContent).toContain('Plan.txt');
  });

  it('starts empty after the follow-up is sent', async () => {
    const onCancel = vi.fn();
    await mount({ onCancel });
    await type('Send this');
    await act(async () => {
      editor().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true }));
    });
    expect(mocks.processAgentTask).toHaveBeenCalledOnce();

    await remount();

    expect(editor().innerHTML).toBe('');
  });

  it('empties a box that stays open when a follow-up is sent another way, and does not save the old text again', async () => {
    await mount();
    await type('Typed but then sent by voice instead');

    act(() => discardComposerDraft('follow-up', 'task-1'));

    expect(editor().innerHTML).toBe('');
    expect(loadComposerDraft('follow-up', 'task-1')).toBeUndefined();
    await type('A fresh thought');
    await remount();
    expect(editor().innerHTML).toBe('A fresh thought');
  });

  it('leaves a box for another task alone when a different task\'s draft is discarded', async () => {
    await mount({ agentTaskId: 'task-a' });
    await type('For task A');

    act(() => discardComposerDraft('follow-up', 'task-b'));

    expect(editor().innerHTML).toBe('For task A');
  });

  it('does not bring back text the reader deleted', async () => {
    await mount();
    await type('Something');
    await type('');

    await remount();

    expect(editor().innerHTML).toBe('');
  });

  it('keeps the draft when the same chain is identified by its root once that is known', async () => {
    await mount({ agentTaskId: 'turn-2' });
    await type('Typed before the root was known');
    await act(async () => {
      root.render(<TextFollowUp agentTaskId="turn-2" rootTaskId="chain-root" onCancel={vi.fn()} alwaysVisible />);
    });

    await remount({ agentTaskId: 'turn-2', rootTaskId: 'chain-root' });

    expect(editor().innerHTML).toBe('Typed before the root was known');
  });

  it('lets a suggested follow-up add to the restored text instead of replacing it', async () => {
    await mount();
    await type('My own line');
    act(() => root.unmount());
    container.remove();
    requestFollowUpLineAdded('task-1', 'Suggested line');
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} alwaysVisible />);
    });

    expect(editor().textContent).toContain('My own line');
    expect(editor().textContent).toContain('Suggested line');
  });
});
