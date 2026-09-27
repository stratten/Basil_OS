import { act, fireEvent, render, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HomeComposer from './HomeComposer';
import {
  enqueueConversationAttachmentError,
  enqueueConversationFilesPicked,
  enqueueConversationVoiceCaptureFinished,
  enqueueConversationVoiceCaptureState,
  enqueueHomeFilesPicked,
  registerConversationFilesPickedHandler,
} from '../services/bridge';

const mocks = vi.hoisted(() => ({
  pickHomeFiles: vi.fn(),
  startHomeVoiceCapture: vi.fn(),
  stopHomeVoiceCapture: vi.fn(),
  cancelHomeVoiceCapture: vi.fn(),
  getReasoningModels: vi.fn().mockResolvedValue({
    models: [{ id: 'default-model', name: 'Default', display_name: 'Default', provider: 'local', is_api_model: false }],
    current_model: 'default-model',
    api_models_enabled: false,
  }),
}));

vi.mock('../services/api', () => ({
  getReasoningModels: mocks.getReasoningModels,
}));

vi.mock('../services/bridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/bridge')>();
  return {
    ...actual,
    pickHomeFiles: mocks.pickHomeFiles,
    startHomeVoiceCapture: mocks.startHomeVoiceCapture,
    stopHomeVoiceCapture: mocks.stopHomeVoiceCapture,
    cancelHomeVoiceCapture: mocks.cancelHomeVoiceCapture,
  };
});

function getEditor(container: HTMLElement): HTMLDivElement {
  const editor = container.querySelector('[role="textbox"][aria-label="Message"]');
  if (!editor) {
    throw new Error('Missing composer editor');
  }
  return editor as HTMLDivElement;
}

describe('HomeComposer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderComposer(onSubmit = vi.fn().mockResolvedValue(undefined)) {
    return render(
      <HomeComposer
        voiceState="idle"
        onSubmit={onSubmit}
      />,
    );
  }

  it('labels the rich editor and icon-only controls', () => {
    const view = renderComposer();

    expect(view.getByRole('textbox', { name: 'Message' })).toBeTruthy();
    expect(view.getByRole('button', { name: 'Attach files or folders' })).toBeTruthy();
    expect(view.getByRole('button', { name: 'Start voice capture' })).toBeTruthy();
    expect(view.getByRole('button', { name: 'Bold' })).toBeTruthy();
  });

  it('submits rich content with display markdown and default model omitted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const view = renderComposer(onSubmit);
    const editor = getEditor(view.container);

    editor.innerHTML = '<strong>Hello</strong> Basil';
    fireEvent.input(editor);
    await userEvent.click(view.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        content: 'Hello Basil',
        displayMarkdown: '**Hello** Basil',
        referencePaths: [],
        modelId: undefined,
      });
    });
  });

  it('submits on Cmd+Enter', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const view = renderComposer(onSubmit);
    const editor = getEditor(view.container);
    editor.textContent = 'Keyboard submit';
    fireEvent.input(editor);
    fireEvent.keyDown(editor, { key: 'Enter', metaKey: true, ctrlKey: false });

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ content: 'Keyboard submit' }));
    });
  });

  it('keeps Shift+Enter as a newline', () => {
    const view = renderComposer();
    const editor = getEditor(view.container);
    editor.innerHTML = 'Line one';
    Object.defineProperty(editor, 'innerText', { configurable: true, value: 'Line one' });
    fireEvent.input(editor);
    fireEvent.keyDown(editor, { key: 'Enter', shiftKey: true });
    expect(view.getByRole('button', { name: 'Send' })).toBeTruthy();
  });

  it('deduplicates picker-delivered paths and allows removal', async () => {
    const view = renderComposer();
    await act(async () => {
      enqueueHomeFilesPicked({ paths: ['/tmp/a.txt', '/tmp/a.txt', '/tmp/b.txt'] });
    });
    expect(view.getByTitle('/tmp/a.txt')).toBeTruthy();
    expect(view.getByTitle('/tmp/b.txt')).toBeTruthy();

    const references = view.container.querySelector('.home-composer-references');
    expect(references).toBeTruthy();
    await userEvent.click(within(references as HTMLElement).getByLabelText('Remove a.txt'));
    expect(view.queryByTitle('/tmp/a.txt')).toBeNull();
    expect(view.getByTitle('/tmp/b.txt')).toBeTruthy();
  });

  it('ignores paths delivered through the Conversation picker chain', async () => {
    const view = renderComposer();
    const conversationHandler = vi.fn();
    const unregisterConversationHandler = registerConversationFilesPickedHandler(conversationHandler);

    await act(async () => {
      enqueueConversationFilesPicked({ paths: ['/tmp/conversation-only.txt'] });
    });

    expect(conversationHandler).toHaveBeenCalledWith(['/tmp/conversation-only.txt']);
    expect(view.queryByTitle('/tmp/conversation-only.txt')).toBeNull();
    expect(view.container.querySelector('.home-composer-references')).toBeNull();
    unregisterConversationHandler();
  });

  it('does not mutate Home state from Conversation voice or attachment callbacks', async () => {
    const view = renderComposer();
    await act(async () => {
      enqueueConversationVoiceCaptureState({ state: 'recording', level: 0.5 });
      enqueueConversationVoiceCaptureFinished({ transcription: 'Should not submit here' });
      enqueueConversationAttachmentError({ message: 'Conversation-only attachment error' });
    });
    expect(view.queryByText('Conversation-only attachment error')).toBeNull();
    expect(view.queryByText('Transcribing')).toBeNull();
    expect(view.getByRole('button', { name: /send/i })).toBeTruthy();
  });

  it('clears drag overlay on drop without reading File.path', () => {
    const view = renderComposer();
    const shell = view.container.querySelector('.home-composer-shell');
    expect(shell).toBeTruthy();
    fireEvent.dragOver(shell!, { dataTransfer: { files: [] } });
    expect(view.getByText('Drop files here')).toBeTruthy();
    fireEvent.drop(shell!, { dataTransfer: { files: [] } });
    expect(view.queryByText('Drop files here')).toBeNull();
  });

  it('retains draft and paths when submission rejects', async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error('failed'));
    const view = renderComposer(onSubmit);
    const editor = getEditor(view.container);
    editor.textContent = 'Keep me';
    fireEvent.input(editor);

    await act(async () => {
      enqueueHomeFilesPicked({ paths: ['/tmp/a.txt'] });
    });

    await userEvent.click(view.getByRole('button', { name: /send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(editor.textContent).toContain('Keep me');
    expect(await view.findByText('a.txt')).toBeTruthy();
  });
});
