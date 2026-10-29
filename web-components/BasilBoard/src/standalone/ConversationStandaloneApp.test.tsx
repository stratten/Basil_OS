import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ConversationStandaloneApp from './ConversationStandaloneApp';

const mocks = vi.hoisted(() => ({
  configureApiBaseUrl: vi.fn(),
  websocketUrl: vi.fn().mockReturnValue('ws://127.0.0.1:8000/ws'),
  connect: vi.fn(),
  disconnect: vi.fn(),
  notifyReady: vi.fn(),
  listConversationPage: vi.fn().mockResolvedValue({ conversations: [], has_more: false, next_cursor: null }),
  onInit: undefined as ((payload: unknown) => void) | undefined,
}));

vi.mock('../services/api', () => ({
  configureApiBaseUrl: mocks.configureApiBaseUrl,
  websocketUrl: mocks.websocketUrl,
  listConversationPage: mocks.listConversationPage,
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: '', api_models_enabled: false }),
}));

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: {
    connect: mocks.connect,
    disconnect: mocks.disconnect,
    subscribe: () => () => {},
    subscribeConnectionState: (handler: (state: string) => void) => {
      handler('closed');
      return () => {};
    },
  },
}));

vi.mock('../capabilities/ConversationWorkspace', () => ({
  default: ({
    originNavigation,
    detachedConversationIds,
  }: {
    originNavigation?: { originId: string };
    detachedConversationIds?: Set<string>;
  }) => (
    <>
      <div data-testid="conversation-origin">{originNavigation?.originId ?? 'none'}</div>
      <div data-testid="detached-conversations">{[...(detachedConversationIds ?? [])].join(',') || 'none'}</div>
    </>
  ),
}));

vi.mock('../services/bridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/bridge')>();
  return {
    ...actual,
    notifyReady: mocks.notifyReady,
    registerBridgeHandlers: (handlers: { onInit: (payload: unknown) => void }) => {
      mocks.onInit = handlers.onInit;
    },
  };
});

describe('ConversationStandaloneApp', () => {
  it('waits for host init, then connects the websocket and renders the workspace chrome', async () => {
    render(<ConversationStandaloneApp />);
    expect(screen.getByText('Waiting for host...')).toBeTruthy();
    expect(mocks.notifyReady).toHaveBeenCalledTimes(1);
    expect(mocks.connect).not.toHaveBeenCalled();

    act(() => {
      mocks.onInit?.({
        apiBaseUrl: 'http://127.0.0.1:9000',
        theme: {
          backgroundPrimary: '#fff', primary: '#003087', secondary: '#33559b', textPrimary: '#001a3d',
        },
        fonts: { fontFamily: 'sans', fontFamilyMedium: 'sans', fontFamilyBold: 'sans' },
      });
    });

    expect(mocks.configureApiBaseUrl).toHaveBeenCalledWith('http://127.0.0.1:9000');
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledWith('ws://127.0.0.1:8000/ws'));
    expect(document.querySelector('.basil-board-detached-title')?.textContent).toBe('Conversation');
    expect(screen.getByTestId('conversation-origin').textContent).toBe('none');

    act(() => {
      window.basilBoardBridge?.onNavigateToAgentTaskOrigin?.({
        originType: 'conversation',
        originId: 'conversation-123',
      });
    });

    expect(screen.getByTestId('conversation-origin').textContent).toBe('conversation-123');

    act(() => {
      window.basilBoardBridge?.onDetachedConversationsChanged?.({
        conversationIds: ['conversation-123'],
      });
    });

    expect(screen.getByTestId('detached-conversations').textContent).toBe('conversation-123');
  });
});
