import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BoardInquirySummary, HomeTurnResponse, WSEvent } from '../contracts';
import type { HomeComposerSubmission } from './HomeComposer';
import { HomeForwardContext, type HomeForwardContextValue } from './HomeForwardContext';
import { HomeRuntimeContext } from './HomeRuntimeContext';
import HomeView, { HOME_ROUTING_STATUS } from './HomeView';

const mocks = vi.hoisted(() => ({
  hydrateBasilBoard: vi.fn(),
  submitHomeTurn: vi.fn(),
  enqueueAgentTaskOriginNavigation: vi.fn(),
  showAgentTaskFromHome: vi.fn(),
  eventHandler: undefined as ((event: WSEvent) => void) | undefined,
}));

vi.mock('../services/api', () => ({
  hydrateBasilBoard: mocks.hydrateBasilBoard,
  submitHomeTurn: mocks.submitHomeTurn,
}));

vi.mock('../services/bridge', () => ({
  enqueueAgentTaskOriginNavigation: mocks.enqueueAgentTaskOriginNavigation,
  showAgentTaskFromHome: mocks.showAgentTaskFromHome,
}));

vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: {
    subscribe: (handler: (event: WSEvent) => void) => {
      mocks.eventHandler = handler;
      return () => {};
    },
  },
}));

const composerSubmission: HomeComposerSubmission = {
  content: 'Book a table',
  displayMarkdown: 'Book a table',
  referencePaths: [],
};

vi.mock('./HomeComposer', () => ({
  default: ({ statusText, onSubmit }: { statusText?: string; onSubmit: (submission: HomeComposerSubmission) => Promise<void> }) => (
    <div>
      <button type="button" onClick={() => void onSubmit(composerSubmission).catch(() => undefined)}>Send</button>
      {statusText ? <div role="status">{statusText}</div> : null}
    </div>
  ),
}));

function inquiry(overrides: Partial<BoardInquirySummary>): BoardInquirySummary {
  return {
    id: 'inq',
    promptText: 'Prompt',
    referencePaths: [],
    routeKind: 'conversation',
    state: 'completed',
    conversationId: 'conv',
    ...overrides,
  };
}

function renderHome(forward: HomeForwardContextValue | null) {
  return render(
    <HomeRuntimeContext.Provider value={{ voiceState: 'idle' }}>
      <HomeForwardContext.Provider value={forward}>
        <HomeView />
      </HomeForwardContext.Provider>
    </HomeRuntimeContext.Provider>,
  );
}

function forwardStub(): HomeForwardContextValue {
  return { forwardTurn: vi.fn(), consumeChatHandoff: vi.fn() };
}

describe('HomeView', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => {
      if (typeof mock === 'function' && 'mockReset' in mock) mock.mockReset();
    });
    mocks.hydrateBasilBoard.mockResolvedValue({ recent_inquiries: [] });
  });

  it('shows an empty state with the composer and no history pane', async () => {
    renderHome(forwardStub());

    expect(await screen.findByText('Nothing yet. Your recent requests will show up here.')).toBeTruthy();
    expect(screen.getByText('Send')).toBeTruthy();
    expect(document.querySelector('.home-history-pane')).toBeNull();
  });

  it('forwards a routed turn to the shell with the submitted text', async () => {
    const response: HomeTurnResponse = {
      inquiry_id: 'inq-1',
      conversation_id: 'conv-1',
      route_kind: 'conversation',
      route_reason: 'Direct',
      state: 'completed',
    };
    mocks.submitHomeTurn.mockResolvedValue(response);
    const forward = forwardStub();
    renderHome(forward);

    fireEvent.click(await screen.findByText('Send'));

    await waitFor(() => expect(forward.forwardTurn).toHaveBeenCalledWith(response, composerSubmission));
  });

  it('shows the routing status while waiting and reports a failure without forwarding', async () => {
    let rejectTurn: (error: Error) => void = () => undefined;
    mocks.submitHomeTurn.mockReturnValue(new Promise((_, reject) => { rejectTurn = reject; }));
    const forward = forwardStub();
    renderHome(forward);

    fireEvent.click(await screen.findByText('Send'));
    expect(await screen.findByText(HOME_ROUTING_STATUS)).toBeTruthy();

    rejectTurn(new Error('Router unavailable'));

    expect((await screen.findByRole('alert')).textContent).toBe('Router unavailable');
    expect(forward.forwardTurn).not.toHaveBeenCalled();
  });

  it('lists at most five recent requests and opens each at its destination', async () => {
    mocks.hydrateBasilBoard.mockResolvedValue({
      recent_inquiries: [
        inquiry({ id: 'a', promptText: 'Chat one', conversationId: 'conv-a' }),
        inquiry({ id: 'b', promptText: 'Agent two', routeKind: 'agent_task', agentTaskId: 'task-b', conversationId: null, state: 'running' }),
        inquiry({ id: 'c', promptText: 'Agent failed', routeKind: 'agent_task', agentTaskId: 'task-c', state: 'failed' }),
        inquiry({ id: 'd', promptText: 'Chat four' }),
        inquiry({ id: 'e', promptText: 'Chat five' }),
        inquiry({ id: 'f', promptText: 'Chat six' }),
      ],
    });
    renderHome(forwardStub());

    expect(await screen.findByText('Chat one')).toBeTruthy();
    expect(screen.queryByText('Chat six')).toBeNull();

    fireEvent.click(screen.getByText('Chat one'));
    expect(mocks.enqueueAgentTaskOriginNavigation).toHaveBeenCalledWith({ originType: 'conversation', originId: 'conv-a' });

    fireEvent.click(screen.getByText('Agent two'));
    expect(mocks.showAgentTaskFromHome).toHaveBeenCalledWith('task-b');

    const failed = screen.getByText('Agent failed').closest('button') as HTMLButtonElement;
    expect(failed.disabled).toBe(true);
    expect(screen.getByText('Did not start')).toBeTruthy();
  });

  it('offers a retry when recent requests fail to load', async () => {
    mocks.hydrateBasilBoard.mockRejectedValueOnce(new Error('offline'));
    renderHome(forwardStub());

    expect(await screen.findByText('Recent requests could not be loaded.')).toBeTruthy();
    mocks.hydrateBasilBoard.mockResolvedValue({ recent_inquiries: [inquiry({ promptText: 'Back again' })] });
    fireEvent.click(screen.getByText('Retry'));

    expect(await screen.findByText('Back again')).toBeTruthy();
  });

  it('refreshes recent requests when an agent task finishes', async () => {
    renderHome(forwardStub());
    await screen.findByText('Nothing yet. Your recent requests will show up here.');
    mocks.hydrateBasilBoard.mockResolvedValue({ recent_inquiries: [inquiry({ promptText: 'Fresh result' })] });

    mocks.eventHandler?.({ event_type: 'agent_task_result', agent_task_id: 'task-1' });

    expect(await screen.findByText('Fresh result')).toBeTruthy();
  });
});
