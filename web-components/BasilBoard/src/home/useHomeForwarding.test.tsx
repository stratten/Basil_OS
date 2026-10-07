import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HomeTurnResponse } from '../contracts';
import type { HomeComposerSubmission } from './HomeComposer';
import { ROUTED_NOTICE_AUTO_DISMISS_MS, useHomeForwarding } from './useHomeForwarding';

const mocks = vi.hoisted(() => ({
  rerouteHomeInquiry: vi.fn(),
  showAgentTaskFromHome: vi.fn(),
}));

vi.mock('../services/api', () => ({ rerouteHomeInquiry: mocks.rerouteHomeInquiry }));
vi.mock('../services/bridge', () => ({ showAgentTaskFromHome: mocks.showAgentTaskFromHome }));

const submission: HomeComposerSubmission = {
  content: 'Plan my week',
  displayMarkdown: 'Plan my week',
  referencePaths: ['/tmp/notes.txt'],
  modelId: 'model-a',
};

function chatResponse(overrides: Partial<HomeTurnResponse> = {}): HomeTurnResponse {
  return {
    inquiry_id: 'inq-1',
    conversation_id: 'conv-1',
    route_kind: 'conversation',
    route_reason: 'Direct question',
    state: 'completed',
    ...overrides,
  };
}

function agentResponse(overrides: Partial<HomeTurnResponse> = {}): HomeTurnResponse {
  return {
    inquiry_id: 'inq-1',
    conversation_id: 'conv-2',
    route_kind: 'agent_task',
    route_reason: 'Needs tools',
    state: 'running',
    agent_task_id: 'task-1',
    ...overrides,
  };
}

function setup(hasChatsTab = true) {
  const selectTab = vi.fn();
  const hook = renderHook(() => useHomeForwarding({
    hasTab: (tabId) => (tabId === 'chats' ? hasChatsTab : false),
    selectTab,
  }));
  return { ...hook, selectTab };
}

describe('useHomeForwarding', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.rerouteHomeInquiry.mockReset();
    mocks.showAgentTaskFromHome.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('hands a chat-routed request to Chats with the first message and shows the notice', () => {
    const { result, selectTab } = setup();

    act(() => result.current.contextValue.forwardTurn(chatResponse(), submission));

    expect(selectTab).toHaveBeenCalledWith('chats');
    expect(result.current.contextValue.chatHandoff).toMatchObject({
      conversationId: 'conv-1',
      content: 'Plan my week',
      filePaths: ['/tmp/notes.txt'],
      modelId: 'model-a',
    });
    expect(result.current.notice).toMatchObject({ inquiryId: 'inq-1', routeKind: 'conversation' });
    expect(mocks.showAgentTaskFromHome).not.toHaveBeenCalled();
  });

  it('forwards an agent-routed request through the native bridge and clears any chat handoff', () => {
    const { result, selectTab } = setup();
    act(() => result.current.contextValue.forwardTurn(chatResponse(), submission));

    act(() => result.current.contextValue.forwardTurn(agentResponse(), submission));

    expect(mocks.showAgentTaskFromHome).toHaveBeenCalledWith('task-1');
    expect(selectTab).toHaveBeenCalledTimes(1);
    expect(result.current.contextValue.chatHandoff).toBeUndefined();
    expect(result.current.notice?.routeKind).toBe('agent_task');
  });

  it('rejects an agent turn that did not start so the composer keeps the request', () => {
    const { result } = setup();

    expect(() => result.current.contextValue.forwardTurn(agentResponse({ state: 'failed' }), submission))
      .toThrow('Basil could not start the agent task.');
    expect(() => result.current.contextValue.forwardTurn(chatResponse({ conversation_id: null }), submission))
      .toThrow();
    expect(result.current.notice).toBeUndefined();
  });

  it('does not navigate when the Chats tab is unavailable', () => {
    const { result, selectTab } = setup(false);

    act(() => result.current.contextValue.forwardTurn(chatResponse(), submission));

    expect(selectTab).not.toHaveBeenCalled();
  });

  it('reroutes a chat to an agent task and forwards again from the same submission', async () => {
    mocks.rerouteHomeInquiry.mockResolvedValue(agentResponse());
    const { result } = setup();
    act(() => result.current.contextValue.forwardTurn(chatResponse(), submission));

    await act(async () => {
      await result.current.reroute();
    });

    expect(mocks.rerouteHomeInquiry).toHaveBeenCalledWith('inq-1', 'agent_task');
    expect(mocks.showAgentTaskFromHome).toHaveBeenCalledWith('task-1');
    expect(result.current.notice).toMatchObject({ routeKind: 'agent_task', rerouting: false });
  });

  it('reroutes an agent task back to a chat with the original text', async () => {
    mocks.rerouteHomeInquiry.mockResolvedValue(chatResponse({ conversation_id: 'conv-3' }));
    const { result, selectTab } = setup();
    act(() => result.current.contextValue.forwardTurn(agentResponse(), submission));

    await act(async () => {
      await result.current.reroute();
    });

    expect(mocks.rerouteHomeInquiry).toHaveBeenCalledWith('inq-1', 'conversation');
    expect(selectTab).toHaveBeenCalledWith('chats');
    expect(result.current.contextValue.chatHandoff).toMatchObject({ conversationId: 'conv-3', content: 'Plan my week' });
  });

  it('keeps the notice and reports the error when a reroute is refused', async () => {
    mocks.rerouteHomeInquiry.mockRejectedValue(new Error('The agent task has already finished'));
    const { result } = setup();
    act(() => result.current.contextValue.forwardTurn(agentResponse(), submission));

    await act(async () => {
      await result.current.reroute();
    });

    expect(result.current.notice).toMatchObject({
      routeKind: 'agent_task',
      rerouting: false,
      error: 'The agent task has already finished',
    });
    act(() => {
      vi.advanceTimersByTime(ROUTED_NOTICE_AUTO_DISMISS_MS * 2);
    });
    expect(result.current.notice).toBeDefined();
  });

  it('dismisses a settled notice automatically and consumes a handoff only by its nonce', () => {
    const { result } = setup();
    act(() => result.current.contextValue.forwardTurn(chatResponse(), submission));
    const nonce = result.current.contextValue.chatHandoff!.nonce;

    act(() => result.current.contextValue.consumeChatHandoff('other'));
    expect(result.current.contextValue.chatHandoff).toBeDefined();
    act(() => result.current.contextValue.consumeChatHandoff(nonce));
    expect(result.current.contextValue.chatHandoff).toBeUndefined();

    act(() => {
      vi.advanceTimersByTime(ROUTED_NOTICE_AUTO_DISMISS_MS + 1);
    });
    expect(result.current.notice).toBeUndefined();
  });
});
