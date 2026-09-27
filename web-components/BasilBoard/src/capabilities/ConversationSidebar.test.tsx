import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationSidebar from './ConversationSidebar';

const chatsCss = readFileSync('src/styles/chats.css', 'utf8');

function renderSidebar(isCollapsed = false, onCollapsedChange = vi.fn()) {
  render(
    <ConversationSidebar
      conversations={[]}
      query=""
      activeConversationIds={new Set()}
      loading={false}
      loadingMore={false}
      hasMore={false}
      isCollapsed={isCollapsed}
      onQueryChange={vi.fn()}
      onRetryLoad={vi.fn()}
      onRetryLoadMore={vi.fn()}
      onLoadMore={vi.fn()}
      onStartNew={vi.fn()}
      onCollapsedChange={onCollapsedChange}
      onSelect={vi.fn()}
      onRequestDelete={vi.fn()}
      onCancelDelete={vi.fn()}
      onConfirmDelete={vi.fn()}
    />,
  );
}

describe('ConversationSidebar', () => {
  it('uses the original new-conversation and sidebar-collapse controls', async () => {
    const onCollapsedChange = vi.fn();
    renderSidebar(false, onCollapsedChange);

    const newConversationSymbol = screen.getByRole('button', { name: 'Start new conversation' }).querySelector('.chats-native-symbol-header');
    const collapseSymbol = screen.getByRole('button', { name: 'Hide conversation history' }).querySelector('.chats-native-symbol-header');
    expect(newConversationSymbol).not.toBeNull();
    expect(collapseSymbol).not.toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Hide conversation history' }));
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it('renders an expand control while the sidebar is collapsed', async () => {
    const onCollapsedChange = vi.fn();
    renderSidebar(true, onCollapsedChange);

    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Show conversation history' })
        .querySelector('.chats-native-symbol-sidebar-expand'),
    ).not.toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Show conversation history' }));
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
  });

  it('keeps the collapsed rail narrow and reveals a compact hover-action rail without idle whitespace', () => {
    expect(chatsCss).toMatch(/\.chats-tab:has\(> \.chats-sidebar-collapsed\)\s*\{[\s\S]*flex-direction: row;/);
    expect(chatsCss).toMatch(/\.chats-tab > \.chats-sidebar\.chats-sidebar-collapsed\s*\{[\s\S]*flex: 0 0 40px;[\s\S]*width: 40px;[\s\S]*min-width: 40px;/);
    expect(chatsCss).toMatch(/\.chats-native-symbol-header\s*\{[\s\S]*width: 12px;[\s\S]*height: 12px;/);
    expect(chatsCss).toMatch(/\.chats-native-symbol-sidebar-expand\s*\{[\s\S]*width: 20px;[\s\S]*height: 20px;/);
    expect(chatsCss).toMatch(/\.chats-sidebar-expand-button\s*\{[\s\S]*width: 32px;[\s\S]*height: 32px;/);
    expect(chatsCss).toMatch(/\.chats-conversation-row\s*\{[\s\S]*z-index: 1;[\s\S]*padding: 8px 12px;/);
    // The actions rail overlaps the row's top-right corner, so it must stack
    // above the row (which sets its own z-index: 1) or the row swallows
    // clicks meant for the delete/detach buttons underneath.
    expect(chatsCss).toMatch(/\.chats-conversation-row-actions\s*\{[\s\S]*z-index: 2;[\s\S]*width: 14px;[\s\S]*flex-direction: column;[\s\S]*opacity: 0;/);
    expect(chatsCss).toMatch(/\.chats-conversation-list > li:hover \.chats-conversation-row-actions,[\s\S]*\.chats-conversation-list > li:focus-within \.chats-conversation-row-actions\s*\{[\s\S]*opacity: 1;/);
    expect(chatsCss).toMatch(/\.chats-conversation-list > li:hover \.chats-conversation-row,[\s\S]*\.chats-conversation-list > li:focus-within \.chats-conversation-row\s*\{[\s\S]*padding-right: 32px;/);
  });

  it('uses hover-only delete and separate-window controls for every conversation row', async () => {
    const onSelect = vi.fn();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'webkit', {
      configurable: true,
      value: { messageHandlers: { basilBoardBridge: { postMessage } } },
    });
    render(
      <ConversationSidebar
        conversations={[{
          id: 'conversation-1',
          title: 'A conversation',
          created_at: '2026-08-02T12:00:00Z',
          updated_at: '2026-08-02T12:00:00Z',
          message_count: 1,
        }]}
        selectedId="conversation-1"
        query=""
        activeConversationIds={new Set()}
        loading={false}
        loadingMore={false}
        hasMore={false}
        isCollapsed={false}
        onQueryChange={vi.fn()}
        onRetryLoad={vi.fn()}
        onRetryLoadMore={vi.fn()}
        onLoadMore={vi.fn()}
        onStartNew={vi.fn()}
        onCollapsedChange={vi.fn()}
        onSelect={onSelect}
        onRequestDelete={vi.fn()}
        onCancelDelete={vi.fn()}
        onConfirmDelete={vi.fn()}
      />,
    );

    const deleteButton = screen.getByRole('button', { name: 'Delete A conversation' });
    const detachButton = screen.getByRole('button', { name: 'Open A conversation in a separate window' });
    expect(deleteButton.querySelector('svg')).toBeTruthy();
    expect(deleteButton.textContent).toBe('');
    expect(detachButton.querySelector('svg')).toBeTruthy();
    expect(detachButton.textContent).toBe('');

    await userEvent.click(detachButton);

    expect(onSelect).not.toHaveBeenCalled();
    expect(postMessage).toHaveBeenCalledWith({
      type: 'openConversationThreadWindow',
      conversationId: 'conversation-1',
    });
  });

  it('opens a conversation in a separate window on row double-click, matching the dedicated button', async () => {
    const onSelect = vi.fn();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'webkit', {
      configurable: true,
      value: { messageHandlers: { basilBoardBridge: { postMessage } } },
    });
    render(
      <ConversationSidebar
        conversations={[{
          id: 'conversation-1',
          title: 'A conversation',
          created_at: '2026-08-02T12:00:00Z',
          updated_at: '2026-08-02T12:00:00Z',
          message_count: 1,
        }]}
        query=""
        activeConversationIds={new Set()}
        loading={false}
        loadingMore={false}
        hasMore={false}
        isCollapsed={false}
        onQueryChange={vi.fn()}
        onRetryLoad={vi.fn()}
        onRetryLoadMore={vi.fn()}
        onLoadMore={vi.fn()}
        onStartNew={vi.fn()}
        onCollapsedChange={vi.fn()}
        onSelect={onSelect}
        onRequestDelete={vi.fn()}
        onCancelDelete={vi.fn()}
        onConfirmDelete={vi.fn()}
      />,
    );

    const row = document.querySelector('.chats-conversation-row') as HTMLButtonElement;
    await userEvent.dblClick(row);

    expect(postMessage).toHaveBeenCalledWith({
      type: 'openConversationThreadWindow',
      conversationId: 'conversation-1',
    });
  });

  it('disables delete only for the active conversation and keeps Start new and Load more enabled while a thread streams', () => {
    renderSidebar(false, vi.fn());

    const startNew = screen.getByRole('button', { name: 'Start new conversation' }) as HTMLButtonElement;
    expect(startNew.disabled).toBe(false);
  });

  it('reveals inline delete on horizontal swipe and blocks it for active agent work', async () => {
    const onRequestDelete = vi.fn();
    render(
      <ConversationSidebar
        conversations={[
          {
            id: 'deletable',
            title: 'Delete me',
            created_at: '2026-08-02T12:00:00Z',
            updated_at: '2026-08-02T12:00:00Z',
            message_count: 1,
          },
          {
            id: 'active-agent',
            title: 'Running work',
            created_at: '2026-08-02T12:00:00Z',
            updated_at: '2026-08-02T12:00:00Z',
            message_count: 1,
            agent_status: { agent_task_id: 'a1', status: 'processing', result_severity: null, is_active: true, updated_at: '2026-08-02T12:00:00Z' },
          },
        ]}
        query=""
        activeConversationIds={new Set()}
        loading={false}
        loadingMore={false}
        hasMore={false}
        isCollapsed={false}
        onQueryChange={vi.fn()}
        onRetryLoad={vi.fn()}
        onRetryLoadMore={vi.fn()}
        onLoadMore={vi.fn()}
        onStartNew={vi.fn()}
        onCollapsedChange={vi.fn()}
        onSelect={vi.fn()}
        onRequestDelete={onRequestDelete}
        onCancelDelete={vi.fn()}
        onConfirmDelete={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole('listitem');
    fireEvent.wheel(rows[0], { deltaX: 80, deltaY: 0 });
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onRequestDelete).toHaveBeenCalledWith('deletable');

    expect(screen.getByRole('button', { name: 'Delete Running work' })).toBeDisabled();
    fireEvent.wheel(rows[1], { deltaX: 80, deltaY: 0 });
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('is memoized so it does not re-render on unrelated parent updates', () => {
    expect((ConversationSidebar as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
  });

  it('shows a status indicator only for a conversation with an active Agent Task', () => {
    render(
      <ConversationSidebar
        conversations={[
          {
            id: 'conversation-with-agent',
            title: 'Has an agent task',
            created_at: '2026-08-02T12:00:00Z',
            updated_at: '2026-08-02T12:00:00Z',
            message_count: 1,
            agent_status: { agent_task_id: 'a1', status: 'processing', result_severity: null, is_active: true, updated_at: '2026-08-02T12:00:00Z' },
          },
          {
            id: 'conversation-without-agent',
            title: 'No agent task',
            created_at: '2026-08-02T12:00:00Z',
            updated_at: '2026-08-02T12:00:00Z',
            message_count: 1,
          },
        ]}
        query=""
        activeConversationIds={new Set()}
        loading={false}
        loadingMore={false}
        hasMore={false}
        isCollapsed={false}
        onQueryChange={vi.fn()}
        onRetryLoad={vi.fn()}
        onRetryLoadMore={vi.fn()}
        onLoadMore={vi.fn()}
        onStartNew={vi.fn()}
        onCollapsedChange={vi.fn()}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onCancelDelete={vi.fn()}
        onConfirmDelete={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole('listitem');
    const rowWithAgent = rows.find((row) => row.textContent?.includes('Has an agent task'));
    const rowWithoutAgent = rows.find((row) => row.textContent?.includes('No agent task'));
    expect(rowWithAgent?.querySelector('.chats-conversation-agent-status')).not.toBeNull();
    expect(rowWithoutAgent?.querySelector('.chats-conversation-agent-status')).toBeNull();
  });
});
