import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ConversationListItem } from '../contracts';
import ConversationSidebar from './ConversationSidebar';

const alpha: ConversationListItem = {
  id: 'alpha', title: 'Alpha', created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z', message_count: 1,
};

function renderSidebar(conversations: ConversationListItem[], loading: boolean) {
  return render(
    <ConversationSidebar
      conversations={conversations}
      query="Al"
      activeConversationIds={new Set()}
      loading={loading}
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
}

describe('ConversationSidebar refresh continuity', () => {
  it('keeps visible conversations and marks the list busy while a reload is in flight', () => {
    const { container } = renderSidebar([alpha], true);
    expect(screen.queryByText('Loading conversations...')).not.toBeInTheDocument();
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(container.querySelector('.chats-conversation-list')?.getAttribute('aria-busy')).toBe('true');
  });

  it('shows the loading row only when no conversations are visible', () => {
    renderSidebar([], true);
    expect(screen.getByRole('status').textContent).toContain('Loading conversations...');
  });
});
