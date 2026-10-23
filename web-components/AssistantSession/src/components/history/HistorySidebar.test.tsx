import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AssistantOutputHistoryEntry } from '../../services/historyApi';
import { HistorySidebar } from './HistorySidebar';

const ENTRY: AssistantOutputHistoryEntry = {
  id: 7,
  outputType: 'assistant_session',
  inputModality: 'voice',
  title: 'Weekly summary',
  outputPreview: 'A long preview that keeps going so the row has to truncate it instead of pushing the delete control out of view',
  timestamp: '2026-09-28T13:54:00Z',
  status: 'completed',
  refinementCount: 0,
  appName: 'Mail',
};

type HistorySidebarProps = Parameters<typeof HistorySidebar>[0];

function renderSidebar(overrides: Partial<HistorySidebarProps> = {}) {
  const props: HistorySidebarProps = {
    entries: [ENTRY],
    selectedId: null,
    onSelect: vi.fn(),
    collapsed: false,
    onToggleCollapsed: vi.fn(),
    filter: 'all',
    onFilterChange: vi.fn(),
    query: '',
    onQueryChange: vi.fn(),
    onDelete: vi.fn(),
    loadState: 'ready',
    errorMessage: null,
    onRetry: vi.fn(),
    refreshing: false,
    actionError: null,
    onDismissActionError: vi.fn(),
    ...overrides,
  };
  const result = render(<HistorySidebar {...props} />);
  return { ...result, props };
}

describe('HistorySidebar', () => {
  it('offers a labeled delete control on every row', () => {
    const { props } = renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Weekly summary' }));
    expect(props.onDelete).toHaveBeenCalledWith(ENTRY);
  });

  it('reveals a delete action with a horizontal swipe and routes it through the same confirmation', () => {
    const { container, props } = renderSidebar();
    const row = container.querySelector<HTMLElement>('.assistant-output-history-sidebar__row')!;
    fireEvent.wheel(row, { deltaX: 80, deltaY: 0 });
    const swipeDelete = container.querySelector<HTMLButtonElement>('.assistant-output-history-sidebar__swipe-delete')!;
    expect(swipeDelete.textContent).toBe('Delete');
    expect(container.querySelector<HTMLElement>('.assistant-output-history-sidebar__row-content')!.style.transform).toBe('translateX(-60px)');
    fireEvent.click(swipeDelete);
    expect(props.onDelete).toHaveBeenCalledWith(ENTRY);
    expect(container.querySelector('.assistant-output-history-sidebar__swipe-delete')).toBeNull();
  });

  it('closes an open swipe instead of selecting when the row is clicked', () => {
    const { container, props } = renderSidebar();
    fireEvent.wheel(container.querySelector<HTMLElement>('.assistant-output-history-sidebar__row')!, { deltaX: 80, deltaY: 0 });
    fireEvent.click(container.querySelector<HTMLButtonElement>('.assistant-output-history-sidebar__row-main')!);
    expect(props.onSelect).not.toHaveBeenCalled();
    expect(container.querySelector('.assistant-output-history-sidebar__swipe-delete')).toBeNull();
    fireEvent.click(container.querySelector<HTMLButtonElement>('.assistant-output-history-sidebar__row-main')!);
    expect(props.onSelect).toHaveBeenCalledWith(7);
  });

  it('renders the row title and truncated output preview as plain text', () => {
    const { container } = renderSidebar({
      entries: [{ ...ENTRY, title: '**Reply** to `q3_report`', outputPreview: '## Summary\n- **Revenue** grew 4%; see the [deck](https://example.com) and the **appen...' }],
    });

    expect(container.querySelector('.assistant-output-history-sidebar__row-title')!.textContent).toBe('Reply to q3_report');
    expect(container.querySelector('.assistant-output-history-sidebar__row-preview')!.textContent).toBe('Summary Revenue grew 4%; see the deck and the appen...');
  });

  it('keeps both sidebar states mounted so collapsing and expanding animate', () => {
    const { container, rerender, props } = renderSidebar();
    const sidebar = container.querySelector<HTMLElement>('.assistant-output-history-sidebar')!;
    expect(sidebar).toHaveClass('basil-collapsible-sidebar', 'is-expanded');
    expect(screen.queryByRole('button', { name: 'Show history' })).toBeNull();
    rerender(<HistorySidebar {...props} collapsed />);
    expect(container.querySelector('.assistant-output-history-sidebar')).toBe(sidebar);
    expect(sidebar).toHaveClass('is-collapsed');
    expect(sidebar.querySelector('.basil-collapsible-sidebar__layer--expanded')).toHaveAttribute('inert');
    expect(sidebar.querySelector('.assistant-output-history-sidebar__search')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
    expect(props.onToggleCollapsed).toHaveBeenCalledTimes(1);
  });
});
