import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem, WSEvent } from '../contracts';
import { enqueueBoardConversationAvailabilityChanged, enqueueDetachedConversationsChanged } from '../services/bridge';
import ChatsTab from './ChatsTab';
import { resetPersistedConversationSessionStateForTests } from './conversationSessionState';

const mocks = vi.hoisted(() => ({
  listConversationPage: vi.fn(),
  getConversationAgentStatuses: vi.fn(),
  getConversationMessages: vi.fn(),
  deleteConversation: vi.fn(),
  getReasoningModels: vi.fn(),
  getConversationWidgetSettings: vi.fn(),
  pickConversationFiles: vi.fn(),
  sendConversationMessage: vi.fn(),
  cancelConversationResponse: vi.fn(),
  saveConversationPastedImages: vi.fn(),
  setBoardFileDropTarget: vi.fn(),
  startConversationVoiceCapture: vi.fn(),
  stopConversationVoiceCapture: vi.fn(),
  cancelConversationVoiceCapture: vi.fn(),
  openExistingAgentTaskWidget: vi.fn(),
  openConversationThreadWindow: vi.fn(),
  activateBoardConversationSurface: vi.fn(),
  deactivateBoardConversationSurface: vi.fn(),
  eventHandlers: [] as Array<(event: WSEvent) => void>,
  connectionHandler: undefined as ((state: 'connecting' | 'open' | 'closed') => void) | undefined,
  filesHandler: undefined as ((paths: string[]) => void) | undefined,
  voiceStateHandler: undefined as ((payload: { state: string; error?: string }) => void) | undefined,
  voiceFinishedHandler: undefined as ((payload: { transcription?: string; error?: string }) => void) | undefined,
  attachmentErrorHandler: undefined as ((message: string) => void) | undefined,
}));

vi.mock('../services/api', () => ({
  listConversationPage: mocks.listConversationPage,
  getConversationAgentStatuses: mocks.getConversationAgentStatuses,
  getConversationMessages: mocks.getConversationMessages,
  deleteConversation: mocks.deleteConversation,
  getReasoningModels: mocks.getReasoningModels,
  getConversationWidgetSettings: mocks.getConversationWidgetSettings,
}));

vi.mock('../services/bridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/bridge')>();
  return {
    ...actual,
    pickConversationFiles: mocks.pickConversationFiles,
    saveConversationPastedImages: mocks.saveConversationPastedImages,
    setBoardFileDropTarget: mocks.setBoardFileDropTarget,
    startConversationVoiceCapture: mocks.startConversationVoiceCapture,
    stopConversationVoiceCapture: mocks.stopConversationVoiceCapture,
    cancelConversationVoiceCapture: mocks.cancelConversationVoiceCapture,
    openExistingAgentTaskWidget: mocks.openExistingAgentTaskWidget,
    openConversationThreadWindow: mocks.openConversationThreadWindow,
    activateBoardConversationSurface: mocks.activateBoardConversationSurface,
    deactivateBoardConversationSurface: mocks.deactivateBoardConversationSurface,
    registerConversationFilesPickedHandler: (handler: (paths: string[]) => void) => {
      mocks.filesHandler = handler;
      return () => {
        if (mocks.filesHandler === handler) mocks.filesHandler = undefined;
      };
    },
    registerConversationVoiceCaptureStateHandler: (
      handler: (payload: { state: string; error?: string }) => void,
    ) => {
      mocks.voiceStateHandler = handler;
      return () => {
        if (mocks.voiceStateHandler === handler) mocks.voiceStateHandler = undefined;
      };
    },
    registerConversationVoiceCaptureFinishedHandler: (
      handler: (payload: { transcription?: string; error?: string }) => void,
    ) => {
      mocks.voiceFinishedHandler = handler;
      return () => {
        if (mocks.voiceFinishedHandler === handler) mocks.voiceFinishedHandler = undefined;
      };
    },
    registerConversationAttachmentErrorHandler: (handler: (message: string) => void) => {
      mocks.attachmentErrorHandler = handler;
      return () => {
        if (mocks.attachmentErrorHandler === handler) mocks.attachmentErrorHandler = undefined;
      };
    },
  };
});

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: {
    subscribe: (handler: (event: WSEvent) => void) => {
      mocks.eventHandlers.push(handler);
      return () => {
        const index = mocks.eventHandlers.indexOf(handler);
        if (index !== -1) mocks.eventHandlers.splice(index, 1);
      };
    },
    subscribeConnectionState: (
      handler: (state: 'connecting' | 'open' | 'closed') => void,
    ) => {
      mocks.connectionHandler = handler;
      handler('open');
      return () => {
        if (mocks.connectionHandler === handler) mocks.connectionHandler = undefined;
      };
    },
    sendConversationMessage: mocks.sendConversationMessage,
    cancelConversationResponse: mocks.cancelConversationResponse,
  },
}));

const conversations = [
  {
    id: 'conversation-1',
    title: 'Alpha',
    created_at: '2026-07-30T12:00:00Z',
    updated_at: '2026-07-30T12:00:00Z',
    message_count: 2,
    last_message_preview: 'Latest alpha message',
  },
  {
    id: 'conversation-2',
    title: 'Beta',
    created_at: '2026-07-30T13:00:00Z',
    updated_at: '2026-07-30T13:00:00Z',
    message_count: 1,
    last_message_preview: 'Latest beta message',
  },
];

function history(
  conversationId: string,
  messages: ConversationMessageItem[],
) {
  return {
    conversation_id: conversationId,
    messages,
    created_at: '2026-07-30T12:00:00Z',
    updated_at: '2026-07-30T12:00:00Z',
    metadata: {},
  };
}

function userMessage(
  id: string,
  content: string,
  metadata: Record<string, unknown> = {},
): ConversationMessageItem {
  return {
    id,
    role: 'user',
    content,
    timestamp: '2026-07-30T12:00:00Z',
    metadata,
  };
}

function assistantMessage(id: string, content: string): ConversationMessageItem {
  return {
    id,
    role: 'assistant',
    content,
    timestamp: '2026-07-30T12:01:00Z',
    metadata: {},
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function editor(): HTMLDivElement {
  return screen.getByRole('textbox', { name: 'Message' }) as HTMLDivElement;
}

async function selectConversation(title = 'Alpha') {
  const titleNode = await screen.findByText(title, {
    selector: '.chats-conversation-title-text',
  });
  const button = titleNode.closest('button');
  if (!button) throw new Error(`Missing conversation button for ${title}`);
  await userEvent.click(button);
}

function emit(event: WSEvent) {
  act(() => {
    for (const handler of mocks.eventHandlers) handler(event);
  });
}

describe('ChatsTab', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    resetPersistedConversationSessionStateForTests();
    mocks.eventHandlers.splice(0);
    mocks.connectionHandler = undefined;
    mocks.filesHandler = undefined;
    mocks.listConversationPage.mockResolvedValue({
      conversations,
      has_more: false,
      next_cursor: null,
    });
    mocks.getConversationAgentStatuses.mockResolvedValue({});
    mocks.getConversationMessages.mockImplementation((conversationId: string) => (
      Promise.resolve(history(conversationId, []))
    ));
    mocks.deleteConversation.mockResolvedValue({ status: 'success', message: 'deleted' });
    mocks.getConversationWidgetSettings.mockResolvedValue({
      status: 'success',
      settings: { default_conversation_only: false },
    });
    mocks.getReasoningModels.mockResolvedValue({
      models: [
        {
          id: 'default-model',
          name: 'Default',
          display_name: 'Default',
          provider: 'local',
          category: 'local',
          is_api_model: false,
        },
        {
          id: 'other-model',
          name: 'Other',
          display_name: 'Other',
          provider: 'api',
          category: 'api',
          is_api_model: true,
        },
      ],
      current_model: 'default-model',
      api_models_enabled: true,
    });
    mocks.sendConversationMessage.mockReturnValue(true);
    mocks.cancelConversationResponse.mockReturnValue(true);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('selects the conversation named by an incoming Conversation origin navigation instead of opening a new one', async () => {
    render(<ChatsTab originNavigation={{ originType: 'conversation', originId: 'conversation-2' }} />);

    await waitFor(() => expect(mocks.getConversationMessages).toHaveBeenCalledWith('conversation-2'));
    await waitFor(() => (
      expect(document.querySelector('.chats-main-header')?.textContent).toContain('Beta')
    ));
  });

  it('ignores an origin navigation meant for a different surface', async () => {
    render(<ChatsTab originNavigation={{ originType: 'todo', originId: 'todo-1' }} />);

    expect(await screen.findByText('New Conversation')).toBeTruthy();
    expect(mocks.getConversationMessages).not.toHaveBeenCalled();
  });

  it('renders an icon-only voice control while idle', async () => {
    render(<ChatsTab />);
    await selectConversation('Alpha');

    const voiceControl = await screen.findByRole('button', { name: 'Voice input' });
    const composer = document.querySelector('.chats-composer');
    const toolbar = document.querySelector('.rich-text-composer-toolbar');
    expect(composer).not.toBeNull();
    expect(composer?.contains(voiceControl)).toBe(true);
    expect(voiceControl.querySelector('svg')).not.toBeNull();
    expect(voiceControl.textContent).not.toContain('Mic');
    for (const title of ['Inline code', 'Code block', 'Bullet list', 'Numbered list']) {
      expect(screen.getByTitle(title).querySelector('svg')).not.toBeNull();
    }
    expect(screen.queryByText('</>')).toBeNull();
    expect(screen.queryByText('[ ]')).toBeNull();

    const composerActions = document.querySelector('.rich-text-composer-actions');
    const modelSelector = screen.getByRole('button', { name: 'Reasoning model' });
    const attachmentControl = screen.getByRole('button', { name: 'Attach files' });
    expect(composerActions).not.toBeNull();
    expect(composerActions?.firstElementChild?.contains(modelSelector)).toBe(true);
    expect(toolbar?.contains(attachmentControl)).toBe(true);
    expect(attachmentControl.querySelector('svg')).not.toBeNull();
    expect(attachmentControl.textContent).toBe('');
  });

  it('opens a new focused composer when no conversation is selected', async () => {
    render(<ChatsTab />);

    expect(await screen.findByText('New Conversation')).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(editor()));
    expect(screen.getByRole('textbox', { name: 'Message' })).toBe(editor());
  });

  it('renders initial loading, empty, error, and retry states', async () => {
    const firstLoad = deferred<{ conversations: typeof conversations; has_more: boolean; next_cursor: null }>();
    mocks.listConversationPage.mockReturnValueOnce(firstLoad.promise);
    const view = render(<ChatsTab />);
    expect(screen.getByRole('status').textContent).toContain('Loading conversations...');

    firstLoad.resolve({ conversations: [], has_more: false, next_cursor: null });
    expect(await screen.findByText('No conversations yet')).toBeTruthy();
    view.unmount();

    mocks.listConversationPage
      .mockRejectedValueOnce(new Error('List failed'))
      .mockResolvedValueOnce({ conversations, has_more: false, next_cursor: null });
    render(<ChatsTab />);
    expect((await screen.findByRole('alert')).textContent).toContain('List failed');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Alpha')).toBeTruthy();
  });

  it('server-searches and ignores an obsolete initial response', async () => {
    vi.useFakeTimers();
    try {
      const initial = deferred<{ conversations: typeof conversations; has_more: boolean; next_cursor: null }>();
      mocks.listConversationPage.mockReturnValueOnce(initial.promise).mockResolvedValueOnce({
        conversations: [conversations[1]],
        has_more: false,
        next_cursor: null,
      });
      render(<ChatsTab />);

      await act(async () => {
        await vi.runAllTimersAsync();
      });
      fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'beta' } });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
      expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
        limit: 30,
        query: 'beta',
      });
      expect(screen.getByText('Beta')).toBeTruthy();

      await act(async () => {
        initial.resolve({ conversations, has_more: false, next_cursor: null });
        await initial.promise;
      });
      expect(screen.queryByText('Alpha')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('appends a next conversation page through the visible Load more control', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce({
        conversations: [conversations[0]],
        has_more: true,
        next_cursor: 'cursor-1',
      })
      .mockResolvedValueOnce({
        conversations: [conversations[1]],
        has_more: false,
        next_cursor: null,
      });
    render(<ChatsTab />);

    expect(await screen.findByText('Alpha')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Load more conversations' }));

    expect(await screen.findByText('Beta')).toBeTruthy();
    expect(mocks.listConversationPage).toHaveBeenLastCalledWith({
      cursor: 'cursor-1',
      limit: 30,
      query: undefined,
    });
    expect(screen.queryByRole('button', { name: 'Load more conversations' })).toBeNull();
  });

  it('loads history, filters system messages, and renders sanitized durable Markdown', async () => {
    mocks.getConversationMessages.mockResolvedValue(history('conversation-1', [
      {
        id: 'system-1',
        role: 'system',
        content: 'Hidden system prompt',
        timestamp: '2026-07-30T11:00:00Z',
        metadata: {},
      },
      userMessage('user-1', 'Plain fallback', {
        display_markdown: '**Formatted** [unsafe](javascript:alert(1))',
      }),
      assistantMessage('assistant-1', '`answer`'),
    ]));
    render(<ChatsTab />);
    await selectConversation();

    expect(await screen.findByText('Formatted')).toBeTruthy();
    const bubble = document.querySelector('.chats-message-user .chats-message-bubble');
    expect(bubble).toBeTruthy();
    expect(bubble?.querySelector('strong')?.textContent).toBe('Formatted');
    expect(screen.queryByText('Hidden system prompt')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('a')?.getAttribute('href')).toBeNull();
    expect(document.querySelector('code')?.textContent).toBe('answer');
  });

  it('submits rich text with the selected default model ID', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.innerHTML = '<strong>Hello</strong> Basil';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(mocks.sendConversationMessage).toHaveBeenCalledWith({
      requestId: expect.any(String),
      messageId: expect.any(String),
      content: 'Hello Basil',
      displayMarkdown: '**Hello** Basil',
      conversationId: 'conversation-1',
      modelId: 'default-model',
      filePaths: [],
      delegationOptOut: false,
      source: 'composer',
      editorHtml: '<strong>Hello</strong> Basil',
    });
    expect(await screen.findByRole('status', { name: /Thinking/ })).toBeTruthy();
  });

  it('starts a new conversation in Conversation only when the default is on', async () => {
    mocks.getConversationWidgetSettings.mockResolvedValue({
      status: 'success',
      settings: { default_conversation_only: true },
    });
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));
    await waitFor(() => {
      expect((screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement).checked).toBe(true);
    });

    const input = editor();
    input.textContent = 'Stay inline by default';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
      expect.objectContaining({ delegationOptOut: true, conversationId: undefined }),
    );
  });

  it('keeps a manual Conversation only change on a new conversation when the default is re-read', async () => {
    mocks.getConversationWidgetSettings.mockResolvedValue({
      status: 'success',
      settings: { default_conversation_only: true },
    });
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));
    const checkbox = screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement;
    await waitFor(() => expect(checkbox.checked).toBe(true));

    await userEvent.click(checkbox);
    const callsBeforeFocus = mocks.getConversationWidgetSettings.mock.calls.length;
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });
    await waitFor(() => expect(mocks.getConversationWidgetSettings.mock.calls.length).toBeGreaterThan(callsBeforeFocus));
    expect(checkbox.checked).toBe(false);

    const input = editor();
    input.textContent = 'Delegate this one';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
      expect.objectContaining({ delegationOptOut: false }),
    );
  });

  it('restores Conversation only from history and ignores the default for existing conversations', async () => {
    mocks.getConversationWidgetSettings.mockResolvedValue({
      status: 'success',
      settings: { default_conversation_only: true },
    });
    mocks.getConversationMessages.mockImplementation((conversationId: string) => Promise.resolve(
      conversationId === 'conversation-1'
        ? history('conversation-1', [
          userMessage('u1', 'Hi', { delegation_opt_out: true }),
          assistantMessage('a1', 'Hello there'),
        ])
        : history(conversationId, [userMessage('u2', 'Older turn')]),
    ));
    render(<ChatsTab />);

    await selectConversation('Alpha');
    expect(await screen.findByText('Hello there')).toBeTruthy();
    await waitFor(() => {
      expect((screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement).checked).toBe(true);
    });

    await selectConversation('Beta');
    expect(await screen.findByText('Older turn')).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement).checked).toBe(false);
  });

  it('keeps composing when the default cannot be read', async () => {
    mocks.getConversationWidgetSettings.mockRejectedValue(new Error('offline'));
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));

    const input = editor();
    input.textContent = 'Still works';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
      expect.objectContaining({ delegationOptOut: false }),
    );
  });

  it('focuses the composer with the caret at the end when the native hotkey asks for it', async () => {
    render(<ChatsTab />);
    await selectConversation('Alpha');
    const input = editor();
    input.textContent = 'Unsent draft';
    fireEvent.input(input);
    const search = screen.getByLabelText('Search conversations');
    search.focus();
    expect(document.activeElement).toBe(search);

    act(() => {
      window.basilBoardBridge?.onFocusConversationComposer?.();
    });

    await waitFor(() => expect(document.activeElement).toBe(editor()));
    const selection = window.getSelection();
    expect(selection?.anchorNode).toBe(editor());
    expect(selection?.anchorOffset).toBe(editor().childNodes.length);
  });

  it('submits delegation opt-out when the checkbox is checked', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const checkbox = screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
    await userEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);

    const input = editor();
    input.textContent = 'Stay inline';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
      expect.objectContaining({ delegationOptOut: true }),
    );
  });

  it('retains delegation opt-out across an unsent retry', async () => {
    mocks.sendConversationMessage.mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<ChatsTab />);
    await selectConversation();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Conversation only' }));
    const input = editor();
    input.textContent = 'Retry me';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText('Conversation is offline. Your draft was not sent.')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(mocks.sendConversationMessage.mock.calls[0][0].delegationOptOut).toBe(true);
    expect(mocks.sendConversationMessage.mock.calls[1][0].delegationOptOut).toBe(true);
  });

  it('retains delegation opt-out across a successful send until manually changed', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const checkbox = screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement;
    await userEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);

    const input = editor();
    input.textContent = 'First send';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(checkbox.checked).toBe(true);

    const submission = mocks.sendConversationMessage.mock.calls[0][0];
    emit({
      event_type: 'conversation_token',
      request_id: submission.requestId,
      conversation_id: 'conversation-1',
      message_id: 'assistant-1',
      token: 'Done',
      chunk_id: 0,
      is_final: true,
    });

    input.textContent = 'Second send';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(mocks.sendConversationMessage.mock.calls[1][0].delegationOptOut).toBe(true);
    expect(checkbox.checked).toBe(true);

    const secondSubmission = mocks.sendConversationMessage.mock.calls[1][0];
    emit({
      event_type: 'conversation_token',
      request_id: secondSubmission.requestId,
      conversation_id: 'conversation-1',
      message_id: 'assistant-2',
      token: 'Done again',
      chunk_id: 0,
      is_final: true,
    });

    await userEvent.click(checkbox);
    expect(checkbox.checked).toBe(false);
  });

  it('retains an unsent draft and delegation opt-out across a Board tab switch away and back', async () => {
    const view = render(<ChatsTab />);
    await selectConversation();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Conversation only' }));

    const input = editor();
    input.textContent = 'Unsent across a tab switch';
    fireEvent.input(input);

    // Switching the Board away from the Conversation tab and back unmounts
    // and remounts ChatsTab (BasilBoardShell only renders the active tab's
    // content), so this simulates that cycle.
    view.unmount();
    render(<ChatsTab />);

    expect(await screen.findByText('Unsent across a tab switch', { selector: '.rich-text-composer-editor' })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: 'Conversation only' })).toHaveProperty('checked', true);
  });

  it('sends the selected non-default model and Cmd+Enter submits', async () => {
    render(<ChatsTab />);
    await selectConversation();
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    await userEvent.click(screen.getByRole('option', { name: 'Other' }));
    const input = editor();
    input.textContent = 'Keyboard send';
    fireEvent.input(input);
    fireEvent.keyDown(input, { key: 'Enter', metaKey: true });

    await waitFor(() => {
      expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
        expect.objectContaining({ content: 'Keyboard send', modelId: 'other-model' }),
      );
    });
  });

  it('deduplicates Conversation attachments and keeps them isolated from Home', async () => {
    render(<ChatsTab />);
    await selectConversation();
    act(() => {
      mocks.filesHandler?.(['/tmp/a.txt', '/tmp/a.txt', '/tmp/b.pdf']);
    });

    expect(screen.getByTitle('/tmp/a.txt')).toBeTruthy();
    expect(screen.getByTitle('/tmp/b.pdf')).toBeTruthy();
    expect(screen.getAllByTitle('/tmp/a.txt')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Remove a.txt' }));
    expect(screen.queryByTitle('/tmp/a.txt')).toBeNull();
    expect(screen.getByTitle('/tmp/b.pdf')).toBeTruthy();
  });

  it('sends opt-out with an attachment-only submission', async () => {
    render(<ChatsTab />);
    await selectConversation();
    act(() => {
      mocks.filesHandler?.(['/tmp/brief.pdf']);
    });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Conversation only' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        content: '',
        filePaths: ['/tmp/brief.pdf'],
        delegationOptOut: true,
      }),
    );
  });

  it('adopts a new conversation only from the matching request', async () => {
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));
    const input = editor();
    input.textContent = 'Create this chat';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_token',
      request_id: 'foreign-request',
      conversation_id: 'foreign-conversation',
      message_id: 'foreign-assistant',
      token: 'wrong',
      chunk_id: 0,
    });
    expect(screen.queryByText('wrong')).toBeNull();

    emit({
      event_type: 'conversation_token',
      request_id: submission.requestId,
      conversation_id: 'created-conversation',
      message_id: 'assistant-1',
      token: 'right',
      chunk_id: 0,
    });
    expect(await screen.findByText('right')).toBeTruthy();

    emit({
      event_type: 'conversation_token',
      request_id: submission.requestId,
      conversation_id: 'created-conversation',
      message_id: 'assistant-1',
      token: '',
      chunk_id: 1,
      is_final: true,
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Send' }).textContent).not.toContain('Sending');
    });
  });

  it('keeps the newest anonymous conversation selected while an earlier one receives its ID', async () => {
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));
    const firstInput = editor();
    firstInput.textContent = 'First conversation';
    fireEvent.input(firstInput);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const firstRequestId = mocks.sendConversationMessage.mock.calls[0][0].requestId;

    await userEvent.click(screen.getByRole('button', { name: 'Start new conversation' }));
    const secondInput = editor();
    secondInput.textContent = 'Second conversation';
    fireEvent.input(secondInput);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const secondRequestId = mocks.sendConversationMessage.mock.calls[1][0].requestId;

    emit({
      event_type: 'conversation_token',
      request_id: firstRequestId,
      conversation_id: 'first-conversation',
      message_id: 'assistant-first',
      token: 'First response',
      chunk_id: 0,
      is_final: true,
    });
    expect(screen.queryByText('First response')).toBeNull();

    emit({
      event_type: 'conversation_token',
      request_id: secondRequestId,
      conversation_id: 'second-conversation',
      message_id: 'assistant-second',
      token: 'Second response',
      chunk_id: 0,
      is_final: false,
    });
    expect(await screen.findByText('Second response')).toBeTruthy();
  });

  it('retains an unsent draft and safely retries the same submission', async () => {
    mocks.sendConversationMessage.mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.innerHTML = '<em>Keep me</em>';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText('Conversation is offline. Your draft was not sent.')).toBeTruthy();
    expect(input.innerHTML).toBe('<em>Keep me</em>');
    const firstSubmission = mocks.sendConversationMessage.mock.calls[0][0];
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(mocks.sendConversationMessage.mock.calls[1][0]).toEqual(firstSubmission);
  });

  it('does not automatically resend an ambiguous stream failure', async () => {
    render(<ChatsTab />);
    await selectConversation();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Conversation only' }));
    const input = editor();
    input.innerHTML = '<strong>Persisted</strong>';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_error',
      request_id: submission.requestId,
      conversation_id: 'conversation-1',
      message: 'Model failed',
    });
    expect(await screen.findByText('Model failed')).toBeTruthy();
    expect(mocks.sendConversationMessage).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Edit and send as a new turn' }));
    expect(editor().innerHTML).toBe('<strong>Persisted</strong>');
    expect(
      (screen.getByRole('checkbox', { name: 'Conversation only' }) as HTMLInputElement).checked,
    ).toBe(true);
    input.textContent = 'Re-sent';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(mocks.sendConversationMessage.mock.calls[1][0]).toEqual(
      expect.objectContaining({ delegationOptOut: true }),
    );
  });

  it('reconciles a terminal chunk gap from durable history', async () => {
    mocks.getConversationMessages
      .mockResolvedValueOnce(history('conversation-1', []))
      .mockResolvedValueOnce(history('conversation-1', [
        assistantMessage('assistant-final', 'Durable response'),
      ]));
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.textContent = 'Stream';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_token',
      request_id: submission.requestId,
      conversation_id: 'conversation-1',
      message_id: 'assistant-1',
      token: 'missed',
      chunk_id: 2,
      is_final: true,
    });

    expect(await screen.findByText('Durable response')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('Part of the streamed response was missed');
  });

  it('ignores stale history after a newer selection', async () => {
    const alpha = deferred<ReturnType<typeof history>>();
    const beta = deferred<ReturnType<typeof history>>();
    mocks.getConversationMessages.mockImplementation((conversationId: string) => (
      conversationId === 'conversation-1' ? alpha.promise : beta.promise
    ));
    render(<ChatsTab />);
    await selectConversation('Alpha');
    await selectConversation('Beta');

    beta.resolve(history('conversation-2', [assistantMessage('beta-answer', 'Beta answer')]));
    expect(await screen.findByText('Beta answer')).toBeTruthy();
    alpha.resolve(history('conversation-1', [assistantMessage('alpha-answer', 'Stale alpha')]));
    await act(async () => alpha.promise);
    expect(screen.queryByText('Stale alpha')).toBeNull();
  });

  it('confirms deletion and handles success and failure', async () => {
    mocks.listConversationPage
      .mockResolvedValueOnce({ conversations, has_more: false, next_cursor: null })
      .mockResolvedValueOnce({
        conversations: [conversations[1]],
        has_more: false,
        next_cursor: null,
      });
    render(<ChatsTab />);
    await screen.findByText('Alpha');
    await userEvent.click(screen.getByRole('button', { name: 'Delete Alpha' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete conversation' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Delete Alpha' }));
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mocks.deleteConversation).toHaveBeenCalledWith('conversation-1'));
    await waitFor(() => expect(screen.queryByText('Latest alpha message')).toBeNull());

    mocks.deleteConversation.mockRejectedValueOnce(new Error('Delete failed'));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Beta' }));
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Delete failed')).toBeTruthy();
  });

  it('copies assistant content and reports clipboard failure', async () => {
    mocks.getConversationMessages.mockResolvedValue(history('conversation-1', [
      assistantMessage('assistant-1', 'Copy this'),
      assistantMessage('assistant-2', 'Fail copy'),
    ]));
    const writeText = vi.mocked(navigator.clipboard.writeText);
    writeText.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('denied'));
    render(<ChatsTab />);
    await selectConversation();
    const copyButtons = await screen.findAllByRole('button', { name: 'Copy rich text' });
    await userEvent.click(copyButtons[0]);
    expect(writeText).toHaveBeenCalledWith('Copy this');
    expect(await screen.findByRole('button', { name: 'Copy rich text copied' })).toBeTruthy();
    await userEvent.click(copyButtons[1]);
    expect(await screen.findByText('Could not copy the response.')).toBeTruthy();
  });

  it('renders long Markdown and overflow-bearing code in stable containers', async () => {
    const longContent = `${'Long content '.repeat(200)}\n\n\`\`\`\n${'x'.repeat(1000)}\n\`\`\``;
    mocks.getConversationMessages.mockResolvedValue(history('conversation-1', [
      assistantMessage('assistant-long', longContent),
    ]));
    const view = render(<ChatsTab />);
    await selectConversation();
    expect(await screen.findByText(/Long content Long content/)).toBeTruthy();
    expect(view.container.querySelector('.chats-message-viewport')).toBeTruthy();
    expect(view.container.querySelector('.chats-message-bubble pre')).toBeTruthy();
  });

  it('serializes Stop and disables a second Stop while cancellation is pending', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.textContent = 'Generate';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(mocks.cancelConversationResponse).toHaveBeenCalledWith(
      submission.requestId,
      'conversation-1',
    );
    expect(screen.getByRole('button', { name: 'Stopping' }).hasAttribute('disabled')).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Stopping' }));
    expect(mocks.cancelConversationResponse).toHaveBeenCalledTimes(1);
  });

  it('reconciles canceled partial history from durable reload', async () => {
    mocks.getConversationMessages
      .mockResolvedValueOnce(history('conversation-1', []))
      .mockResolvedValueOnce(history('conversation-1', [
        userMessage('user-1', 'Partial turn'),
        {
          id: 'assistant-1',
          role: 'assistant',
          content: 'Partial answer',
          timestamp: '2026-07-30T12:01:00Z',
          metadata: { canceled: true },
        },
      ]));
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.textContent = 'Partial turn';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_canceled',
      request_id: submission.requestId,
      conversation_id: 'conversation-1',
      message_id: 'assistant-1',
      canceled: true,
    });

    await waitFor(() => expect(mocks.getConversationMessages).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Partial answer')).toBeTruthy();
    expect(await screen.findByText('Canceled')).toBeTruthy();
  });

  it('preserves active processing when cancellation is rejected', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.textContent = 'Keep streaming';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_cancel_rejected',
      request_id: submission.requestId,
      message: 'Stop rejected',
    });

    expect(await screen.findByText('Stop rejected')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy();
  });

  it('sends voice transcription immediately without clearing typed draft or attachments', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    input.innerHTML = '<strong>Keep</strong> draft';
    fireEvent.input(input);
    act(() => {
      mocks.filesHandler?.(['/tmp/pending.txt']);
    });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Conversation only' }));

    act(() => {
      mocks.voiceFinishedHandler?.({ transcription: 'Voice <special> & chars' });
    });

    await waitFor(() => {
      expect(mocks.sendConversationMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          content: 'Voice <special> & chars',
          source: 'voice',
          filePaths: [],
          delegationOptOut: true,
        }),
      );
    });
    expect(input.innerHTML).toBe('<strong>Keep</strong> draft');
    expect(screen.getByTitle('/tmp/pending.txt')).toBeTruthy();
  });

  it('forwards pasted image data URLs to native staging', async () => {
    const readAsDataURL = vi.fn(function read(this: FileReader) {
      queueMicrotask(() => {
        Object.defineProperty(this, 'result', {
          configurable: true,
          value: 'data:image/png;base64,abc',
        });
        this.onload?.(new ProgressEvent('load') as ProgressEvent<FileReader>);
      });
    });
    vi.stubGlobal('FileReader', class {
      onload: ((event: ProgressEvent<FileReader>) => void) | null = null;
      onerror: ((event: ProgressEvent<FileReader>) => void) | null = null;
      readAsDataURL = readAsDataURL;
    });

    render(<ChatsTab />);
    await selectConversation();
    const input = editor();
    const file = new File(['png'], 'paste.png', { type: 'image/png' });
    fireEvent.paste(input, {
      clipboardData: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(mocks.saveConversationPastedImages).toHaveBeenCalledWith(['data:image/png;base64,abc']);
    });
    vi.unstubAllGlobals();
  });

  it('arms and clears the Conversation drag target', async () => {
    render(<ChatsTab />);
    await selectConversation();
    const region = document.querySelector('.chats-composer-region');
    expect(region).toBeTruthy();
    fireEvent.dragOver(region!, { dataTransfer: { files: [] } });
    expect(mocks.setBoardFileDropTarget).toHaveBeenCalledWith('conversation');
    fireEvent.dragLeave(region!, { relatedTarget: document.body });
    expect(mocks.setBoardFileDropTarget).toHaveBeenLastCalledWith();
  });

  it('adopts a new Agent Task conversation, shows the status card, then narration replaces it', async () => {
    render(<ChatsTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start new conversation' }));
    const input = editor();
    input.textContent = 'Plan my week';
    fireEvent.input(input);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const submission = mocks.sendConversationMessage.mock.calls[0][0];

    emit({
      event_type: 'conversation_agent_status',
      request_id: submission.requestId,
      conversation_id: 'created-conversation',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'running',
      status_text: 'Agent task is working.',
    });

    expect(await screen.findByRole('status', { name: 'Agent task in progress' })).toBeTruthy();
    expect(screen.getByText('Agent task is working.')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Open Agent Task' }));
    expect(mocks.openExistingAgentTaskWidget).toHaveBeenCalledWith('task-1');

    emit({
      event_type: 'conversation_token',
      conversation_id: 'created-conversation',
      message_id: 'assistant-agent-1',
      token: 'Here is your plan.',
      chunk_id: 0,
      is_final: true,
    });

    expect(await screen.findByText('Here is your plan.')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Agent task in progress' })).toBeTruthy();

    emit({
      event_type: 'conversation_agent_status',
      conversation_id: 'created-conversation',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'completed',
      terminal_outcome: 'Agent task completed.',
      narration_state: 'completed',
    });
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
    });
    expect(document.querySelectorAll('.chats-message')).toHaveLength(2);
  });

  it('recovers a durable Agent Task status card from persisted history after reload', async () => {
    mocks.getConversationMessages.mockResolvedValue(history('conversation-1', [
      userMessage('user-1', 'Plan my week'),
      {
        id: 'assistant-agent-1',
        role: 'assistant',
        content: '',
        timestamp: '2026-07-30T12:01:00Z',
        metadata: {
          conversation_turn: {
            route: 'agent_task',
            lifecycle: 'running',
            agent_task_id: 'task-1',
            terminal_outcome: null,
          },
        },
      },
    ]));
    render(<ChatsTab />);
    await selectConversation();

    expect(await screen.findByRole('status', { name: 'Agent task in progress' })).toBeTruthy();

    emit({
      event_type: 'conversation_agent_status',
      conversation_id: 'conversation-1',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'running',
      status_text: 'Still working.',
    });
    expect(await screen.findByText('Still working.')).toBeTruthy();

    emit({
      event_type: 'conversation_agent_status',
      conversation_id: 'conversation-1',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'completed',
      terminal_outcome: 'Agent task completed.',
    });
    expect(await screen.findByRole('status', { name: 'Agent task completed' })).toBeTruthy();

    emit({
      event_type: 'conversation_agent_status',
      conversation_id: 'conversation-1',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'running',
      status_text: 'Stale regression attempt.',
    });
    expect(screen.queryByText('Stale regression attempt.')).toBeNull();
    expect(await screen.findByRole('status', { name: 'Agent task completed' })).toBeTruthy();
  });

  it('keeps an in-flight Agent Task card visible after navigating away and back through stale history', async () => {
    mocks.getConversationMessages.mockImplementation((conversationId: string) => Promise.resolve(
      history(conversationId, conversationId === 'conversation-1'
        ? [
          userMessage('user-1', 'Plan my week'),
          {
            id: 'assistant-agent-1',
            role: 'assistant',
            content: '',
            timestamp: '2026-07-30T12:01:00Z',
            metadata: {},
          },
        ]
        : []),
    ));
    render(<ChatsTab />);
    await selectConversation('Alpha');
    emit({
      event_type: 'conversation_agent_status',
      conversation_id: 'conversation-1',
      placeholder_message_id: 'assistant-agent-1',
      agent_task_id: 'task-1',
      lifecycle: 'running',
      status_text: 'Agent task is working.',
    });
    expect(await screen.findByText('Agent task is working.')).toBeTruthy();

    await selectConversation('Beta');
    await selectConversation('Alpha');

    expect(await screen.findByRole('status', { name: 'Agent task in progress' })).toBeTruthy();
    expect(screen.getByText('Agent task is working.')).toBeTruthy();
  });

  it('activates the Board Conversation surface on mount and deactivates on unmount', async () => {
    const view = render(<ChatsTab />);
    await selectConversation('Alpha');
    expect(mocks.activateBoardConversationSurface).toHaveBeenCalledTimes(1);
    expect(mocks.deactivateBoardConversationSurface).not.toHaveBeenCalled();

    view.unmount();
    expect(mocks.deactivateBoardConversationSurface).toHaveBeenCalledTimes(1);
  });

  it('replaces the workspace with a placeholder when the standalone window becomes authoritative', async () => {
    render(<ChatsTab />);
    await selectConversation('Alpha');

    act(() => {
      enqueueBoardConversationAvailabilityChanged({ availability: 'unavailable' });
    });

    expect(screen.getByText('Conversation is open in a separate window.')).toBeTruthy();
    expect(screen.queryByText('Alpha')).toBeNull();

    act(() => {
      enqueueBoardConversationAvailabilityChanged({ availability: 'available' });
    });
    // The previously selected conversation is restored (not just the list),
    // so "Alpha" now correctly appears both in the sidebar row and in the
    // main header title.
    const sidebar = await screen.findByLabelText('Conversation history');
    expect(await within(sidebar).findByText('Alpha')).toBeTruthy();
    expect(document.querySelector('.chats-main-header')?.textContent).toContain('Alpha');
  });

  it('shows a per-conversation placeholder only for the specific conversation open in its own window, keeping the sidebar usable', async () => {
    render(<ChatsTab />);
    await selectConversation('Alpha');

    act(() => {
      enqueueDetachedConversationsChanged({ conversationIds: ['conversation-1'] });
    });

    expect(screen.getByText('This conversation is open in a separate window.')).toBeTruthy();
    const sidebar = await screen.findByLabelText('Conversation history');
    expect(within(sidebar).getByText('Alpha')).toBeTruthy();
    expect(within(sidebar).getByText('Beta')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Bring window to front' }));
    expect(mocks.openConversationThreadWindow).toHaveBeenCalledWith('conversation-1');

    await selectConversation('Beta');
    expect(screen.queryByText('This conversation is open in a separate window.')).toBeNull();

    await selectConversation('Alpha');
    expect(screen.getByText('This conversation is open in a separate window.')).toBeTruthy();

    act(() => {
      enqueueDetachedConversationsChanged({ conversationIds: [] });
    });
    expect(screen.queryByText('This conversation is open in a separate window.')).toBeNull();
  });

  it('streams two independently selected conversations without freezing navigation or cross-owning Stop', async () => {
    mocks.getConversationMessages.mockImplementation((conversationId: string) => (
      Promise.resolve(history(conversationId, []))
    ));
    render(<ChatsTab />);

    await selectConversation('Alpha');
    const alphaEditor = editor();
    alphaEditor.innerHTML = 'Tell me about Alpha';
    fireEvent.input(alphaEditor);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const alphaRequestId = mocks.sendConversationMessage.mock.calls[0][0].requestId as string;

    await selectConversation('Beta');
    const betaEditor = editor();
    betaEditor.innerHTML = 'Tell me about Beta';
    fireEvent.input(betaEditor);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    const betaRequestId = mocks.sendConversationMessage.mock.calls[1][0].requestId as string;

    expect(alphaRequestId).not.toBe(betaRequestId);

    emit({
      event_type: 'conversation_token',
      request_id: betaRequestId,
      conversation_id: 'conversation-2',
      message_id: 'assistant-beta',
      chunk_id: 0,
      token: 'Beta reply',
      is_final: false,
    } as WSEvent);
    expect(await screen.findByText('Beta reply')).toBeTruthy();

    await selectConversation('Alpha');
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeTruthy();
    expect(screen.queryByText('Beta reply')).toBeNull();

    emit({
      event_type: 'conversation_token',
      request_id: alphaRequestId,
      conversation_id: 'conversation-1',
      message_id: 'assistant-alpha',
      chunk_id: 0,
      token: 'Alpha reply',
      is_final: false,
    } as WSEvent);
    expect(await screen.findByText('Alpha reply')).toBeTruthy();

    const alphaTitle = await screen.findByText('Alpha', { selector: '.chats-conversation-title-text' });
    const alphaRow = alphaTitle.closest('button') as HTMLButtonElement | null;
    expect(alphaRow).not.toBeNull();
    expect(alphaRow?.disabled).toBe(false);
    const betaDeleteButton = screen.getAllByRole('button', { name: /Delete Beta/ })[0] as HTMLButtonElement;
    expect(betaDeleteButton.disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Start new conversation' }) as HTMLButtonElement).disabled).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(mocks.cancelConversationResponse).toHaveBeenCalledWith(alphaRequestId, 'conversation-1');

    await selectConversation('Beta');
    emit({
      event_type: 'conversation_token',
      request_id: betaRequestId,
      conversation_id: 'conversation-2',
      message_id: 'assistant-beta',
      chunk_id: 1,
      token: ' continues',
      is_final: true,
    } as WSEvent);
    expect(await screen.findByText('Beta reply continues')).toBeTruthy();
  });
});
