// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TextFollowUp from './TextFollowUp';

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
  },
}));

vi.mock('../services/bridge', () => ({
  registerFilesPickedHandler: mocks.registerFilesPickedHandler,
  pickFiles: mocks.pickFiles,
}));

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

afterEach(() => {
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

    expect(container.textContent).toContain('References');
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
    expect(mocks.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
      reference_paths: ['/tmp/Karpathy Transcript.txt'],
    }));
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
