import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { BasilBoardTab } from '../contracts';
import BasilBoardShell from './BasilBoardShell';

vi.mock('../services/bridge', () => ({
  bringBasilBoardTabToFront: vi.fn(),
  detachBasilBoardTab: vi.fn(),
  openNativeBasilBoardTabWindow: vi.fn(),
  reportBoardChromeGeometry: vi.fn(),
  requestWindowClose: vi.fn(),
  requestWindowMinimize: vi.fn(),
  registerDetachedTabsChangedHandler: vi.fn(() => () => {}),
}));
vi.mock('../home/HomeView', () => ({ default: () => <div>Home content</div> }));
vi.mock('../todos/TodoView', () => ({ default: () => <div>To-Do content</div> }));
vi.mock('../capabilities/ChatsTab', () => ({
  default: ({ originNavigation }: { originNavigation?: { originType: string; originId: string } }) => (
    <div>Chats content{originNavigation ? `: ${originNavigation.originId}` : ''}</div>
  ),
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
