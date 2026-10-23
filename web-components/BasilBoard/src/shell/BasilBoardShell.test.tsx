import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BasilBoardTab, HomeTurnResponse } from '../contracts';
import { HomeRuntimeContext } from '../home/HomeRuntimeContext';
import { useHomeForward } from '../home/HomeForwardContext';
import { ROUTED_NOTICE_AUTO_DISMISS_MS } from '../home/useHomeForwarding';
import BasilBoardShell from './BasilBoardShell';

const mocks = vi.hoisted(() => ({
  navigateBoardTab: undefined as ((payload: { tabId: string }) => void) | undefined,
  showAgentTaskFromHome: vi.fn(),
  rerouteHomeInquiry: vi.fn(),
}));

vi.mock('../services/bridge', () => ({
  bringBasilBoardTabToFront: vi.fn(),
  detachBasilBoardTab: vi.fn(),
  openNativeBasilBoardTabWindow: vi.fn(),
  reportBoardChromeGeometry: vi.fn(),
  requestWindowClose: vi.fn(),
  requestWindowMinimize: vi.fn(),
  registerDetachedTabsChangedHandler: vi.fn(() => () => {}),
  registerBoardTabNavigationHandler: vi.fn((handler: (payload: { tabId: string }) => void) => {
    mocks.navigateBoardTab = handler;
    return () => {};
  }),
  showAgentTaskFromHome: mocks.showAgentTaskFromHome,
}));
vi.mock('../services/api', () => ({ rerouteHomeInquiry: mocks.rerouteHomeInquiry }));

const chatResponse: HomeTurnResponse = {
  inquiry_id: 'inq-1',
  conversation_id: 'conv-1',
  route_kind: 'conversation',
  route_reason: 'Direct',
  state: 'completed',
};

vi.mock('../home/HomeView', () => ({
  default: function MockHome() {
    const forward = useHomeForward();
    return (
      <div>
        Home content
        <button
          type="button"
          onClick={() => forward?.forwardTurn(chatResponse, { content: 'Hello', displayMarkdown: 'Hello', referencePaths: [] })}
        >
          Mock submit
        </button>
      </div>
    );
  },
}));
vi.mock('../todos/TodoView', () => ({ default: () => <div>To-Do content</div> }));
vi.mock('../capabilities/AgentTasksHostPlaceholder', () => ({ default: () => <div>Agents content</div> }));
vi.mock('../capabilities/ChatsTab', () => ({
  default: function MockChats({ originNavigation }: { originNavigation?: { originType: string; originId: string } }) {
    const forward = useHomeForward();
    return (
      <div>
        Chats content{originNavigation ? `: ${originNavigation.originId}` : ''}
        {forward?.chatHandoff ? ` handoff:${forward.chatHandoff.conversationId}` : ''}
      </div>
    );
  },
}));

const tabs: BasilBoardTab[] = [
  {
    id: 'home',
    title: 'Home',
    position: 0,
    tab_kind: 'home',
    status: 'active',
    configuration: {},
  },
  {
    id: 'todos',
    title: 'To-Dos',
    position: 1,
    tab_kind: 'capability',
    status: 'active',
    configuration: { capability_id: 'todos.workspace' },
  },
  {
    id: 'chats',
    title: 'Chats',
    position: 2,
    tab_kind: 'capability',
    status: 'active',
    configuration: { capability_id: 'conversations.history' },
  },
  {
    id: 'agent_tasks',
    title: 'Agents',
    position: 3,
    tab_kind: 'capability',
    status: 'active',
    configuration: { capability_id: 'agent_tasks.history' },
  },
];

describe('BasilBoardShell Agent Task origin navigation', () => {
  it('activates the To-Dos tab for a To-Do origin', async () => {
    render(
      <BasilBoardShell
        tabs={tabs}
        originNavigation={{ originType: 'todo', originId: 'todo-1' }}
      />,
    );

    await waitFor(() => expect(screen.getByText('To-Do content')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /To-Dos/i })).toHaveAttribute('aria-current', 'page');
  });

  it('activates the Chats tab and forwards the origin for a Conversation origin', async () => {
    render(
      <BasilBoardShell
        tabs={tabs}
        originNavigation={{ originType: 'conversation', originId: 'conversation-1' }}
      />,
    );

    await waitFor(() => expect(screen.getByText('Chats content: conversation-1')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Chats/i })).toHaveAttribute('aria-current', 'page');
  });

  it('preserves the current tab for an unsupported destination', () => {
    render(
      <BasilBoardShell
        tabs={tabs}
        originNavigation={{ originType: 'meeting', originId: 'meeting-1' }}
      />,
    );

    expect(screen.getByText('Home content')).toBeInTheDocument();
  });
});

describe('BasilBoardShell Home forwarding', () => {
  beforeEach(() => {
    mocks.navigateBoardTab = undefined;
    mocks.showAgentTaskFromHome.mockReset();
    mocks.rerouteHomeInquiry.mockReset();
  });

  it('follows a tab navigation request from the native host and ignores unknown tabs', () => {
    render(<BasilBoardShell tabs={tabs} />);

    act(() => mocks.navigateBoardTab?.({ tabId: 'missing' }));
    expect(screen.getByText('Home content')).toBeInTheDocument();

    act(() => mocks.navigateBoardTab?.({ tabId: 'agent_tasks' }));
    expect(screen.getByRole('button', { name: /Agents/i })).toHaveAttribute('aria-current', 'page');
  });

  it('forwards a Home chat to Chats with a routed notice that can send it to an agent task instead', async () => {
    mocks.rerouteHomeInquiry.mockResolvedValue({
      inquiry_id: 'inq-1',
      conversation_id: 'conv-2',
      route_kind: 'agent_task',
      route_reason: 'Corrected',
      state: 'running',
      agent_task_id: 'task-9',
    } satisfies HomeTurnResponse);
    render(<BasilBoardShell tabs={tabs} />);

    fireEvent.click(screen.getByText('Mock submit'));

    expect(screen.getByText('Chats content handoff:conv-1')).toBeInTheDocument();
    expect(screen.getByText('Sent to Chats as a conversation.')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Send as agent task instead'));

    await waitFor(() => expect(mocks.showAgentTaskFromHome).toHaveBeenCalledWith('task-9'));
    expect(mocks.rerouteHomeInquiry).toHaveBeenCalledWith('inq-1', 'agent_task');
    expect(await screen.findByText('Started as an agent task.')).toBeInTheDocument();
    expect(screen.getByText('Answer in a chat instead')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Dismiss'));
    expect(screen.queryByText('Started as an agent task.')).toBeNull();
  });

  it('keeps the routed notice while the pointer or focus is on it, then dismisses it after the delay', () => {
    vi.useFakeTimers();
    try {
      render(<BasilBoardShell tabs={tabs} />);
      fireEvent.click(screen.getByText('Mock submit'));
      const notice = screen.getByText('Sent to Chats as a conversation.').closest('.routed-notice') as HTMLElement;

      fireEvent.mouseEnter(notice);
      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      expect(screen.getByText('Sent to Chats as a conversation.')).toBeInTheDocument();

      fireEvent.mouseLeave(notice);
      act(() => {
        vi.advanceTimersByTime(ROUTED_NOTICE_AUTO_DISMISS_MS + 1);
      });
      expect(screen.queryByText('Sent to Chats as a conversation.')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('forwards a natively submitted voice turn the same way as a typed one', () => {
    const voiceTurn = {
      version: 1,
      response: chatResponse,
      submission: { content: 'Spoken request', displayMarkdown: 'Spoken request', referencePaths: [] },
    };
    const { rerender } = render(
      <HomeRuntimeContext.Provider value={{ voiceState: 'idle' }}>
        <BasilBoardShell tabs={tabs} />
      </HomeRuntimeContext.Provider>,
    );
    expect(screen.getByText('Home content')).toBeInTheDocument();

    rerender(
      <HomeRuntimeContext.Provider value={{ voiceState: 'idle', voiceTurn }}>
        <BasilBoardShell tabs={tabs} />
      </HomeRuntimeContext.Provider>,
    );

    expect(screen.getByText('Chats content handoff:conv-1')).toBeInTheDocument();
  });
});
