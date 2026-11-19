import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ConversationSidebar from './ConversationSidebar';
import { EMPTY_CONVERSATION_FILTERS, type ConversationFilters } from './conversationFilters';
import type { ConversationSidebarFilters } from './ConversationFilterControls';

const conversation = {
  id: 'conversation-1',
  title: 'Lisbon offsite',
  created_at: '2026-08-02T12:00:00Z',
  updated_at: '2026-08-02T12:00:00Z',
  message_count: 2,
  last_message_preview: 'Booked',
};

function filterControls(filters: ConversationFilters = EMPTY_CONVERSATION_FILTERS, expanded = false): ConversationSidebarFilters {
  return { filters, expanded, onChange: vi.fn(), onClear: vi.fn(), onToggle: vi.fn() };
}

function renderSidebar(controls: ConversationSidebarFilters | undefined, conversations = [conversation]) {
  render(
    <ConversationSidebar
      conversations={conversations}
      query=""
      activeConversationIds={new Set()}
      loading={false}
      loadingMore={false}
      hasMore={false}
      isCollapsed={false}
      filterControls={controls}
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

describe('ConversationSidebar filters', () => {
  it('shows no filter button when the list cannot be filtered', () => {
    renderSidebar(undefined);
    expect(screen.queryByRole('button', { name: /Conversation filters/ })).toBeNull();
  });

  it('puts the filter button beside the search field and toggles the panel', () => {
    const controls = filterControls();
    renderSidebar(controls);
    const button = screen.getByRole('button', { name: 'Conversation filters' });
    expect(button.closest('.chats-search-row')?.querySelector('.chats-search')).not.toBeNull();
    expect(button.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(button);
    expect(controls.onToggle).toHaveBeenCalledTimes(1);
  });

  it('badges the button with the number of active filters', () => {
    renderSidebar(filterControls({ ...EMPTY_CONVERSATION_FILTERS, agentWork: 'failed', length: 'multi' }));
    const button = screen.getByRole('button', { name: 'Conversation filters, 2 active' });
    expect(button.textContent).toBe('2');
  });

  it('renders the date range, agent work and length fields in the expanded panel and reports a date change', () => {
    const controls = filterControls(EMPTY_CONVERSATION_FILTERS, true);
    renderSidebar(controls);
    expect(screen.getByRole('region', { name: 'Conversation filters' })).not.toBeNull();
    expect(screen.getByLabelText('Agent work')).not.toBeNull();
    expect(screen.getByLabelText('Length')).not.toBeNull();
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-03-02' } });
    expect(controls.onChange).toHaveBeenCalledWith({ startDate: '2026-03-02' });
  });

  it('shows a filtered-empty state with Clear when the filters leave nothing', () => {
    const controls = filterControls({ ...EMPTY_CONVERSATION_FILTERS, agentWork: 'active' });
    renderSidebar(controls, []);
    expect(screen.getByText('No conversations match these filters')).not.toBeNull();
    expect(screen.queryByText('No conversations yet')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(controls.onClear).toHaveBeenCalledTimes(1);
  });

  it('keeps the plain empty state when no filter is active', () => {
    renderSidebar(filterControls(), []);
    expect(screen.getByText('No conversations yet')).not.toBeNull();
  });
});
