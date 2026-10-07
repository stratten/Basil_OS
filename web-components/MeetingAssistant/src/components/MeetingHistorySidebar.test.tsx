import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingListItemDTO } from '../bridge/types';
import MeetingHistorySidebar from './MeetingHistorySidebar';

const intents = vi.hoisted(() => ({
  deleteMeeting: vi.fn(),
  loadMoreMeetings: vi.fn(),
  selectMeeting: vi.fn(),
  setMeetingSearch: vi.fn(),
  setMeetingSearchFilters: vi.fn(),
  setSidebarCollapsed: vi.fn(),
  startNewMeeting: vi.fn(),
  viewAnalysis: vi.fn(),
}));

vi.mock('../bridge/meetingBridge', () => intents);

const meeting: MeetingListItemDTO = {
  id: 'meeting-1',
  name: 'Stand Up',
  purpose: null,
  participants: [],
  startTime: '2026-08-14T15:02:00Z',
  endTime: null,
  durationSeconds: 2940,
  isPostProcessed: true,
  analysisSummary: { count: 1, latestFilename: 'analysis.json', latestTimestamp: 'now', pendingActionCount: 2 },
  sessionId: null,
  audioSource: null,
  members: null,
  formattedDate: '2026-08-14 11:02 am',
  shortFormattedDuration: '49m',
  relativeDateString: 'Yesterday, 11:02 AM',
};

const filters = {
  queryMode: 'and' as const,
  name: '', nameMode: 'and' as const,
  purpose: '', purposeMode: 'and' as const,
  participants: '', participantsMode: 'and' as const,
  transcript: '', transcriptMode: 'and' as const,
  source: '', sourceMode: 'and' as const,
  startDate: null, endDate: null,
  processing: 'any' as const,
  analysis: 'any' as const,
};

describe('MeetingHistorySidebar', () => {
  beforeEach(() => Object.values(intents).forEach((mock) => mock.mockReset()));

  it('renders canonical header controls and preference-aware row metadata', () => {
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start new meeting' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide meeting history' })).toBeInTheDocument();
    expect(screen.getByText('2026-08-14 11:02 am')).toBeInTheDocument();
    expect(screen.queryByText('Yesterday, 11:02 AM')).not.toBeInTheDocument();
    expect(screen.getByText('49m')).toBeInTheDocument();
    expect(screen.getByText('Processed')).toBeInTheDocument();
    expect(screen.getByText('2 pending')).toBeInTheDocument();
  });

  it('opens analysis without selecting the meeting row', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    await user.click(screen.getByRole('button', { name: 'Open latest analysis for Stand Up' }));
    expect(intents.viewAnalysis).toHaveBeenCalledWith('analysis.json');
    expect(intents.selectMeeting).not.toHaveBeenCalled();
  });

  it('keeps the delete action available for the selected meeting', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={meeting.id} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    await user.click(screen.getByRole('button', { name: 'Delete Stand Up' }));
    expect(screen.getByText('Delete this meeting?')).toBeInTheDocument();
  });

  it('replaces the row with an inline confirmation that can be cancelled or confirmed', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    await user.click(screen.getByRole('button', { name: 'Delete Stand Up' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete meeting' });
    expect(dialog.closest('li')?.querySelector('.meeting-history-item-name')).toBeNull();
    expect(screen.queryByText('Stand Up')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByText('Stand Up')).toBeInTheDocument();
    expect(intents.deleteMeeting).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Delete Stand Up' }));
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(intents.deleteMeeting).toHaveBeenCalledWith('meeting-1');
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('reveals delete on horizontal swipe and disallows deletion of the active analysis owner', async () => {
    const user = userEvent.setup();
    const view = render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    fireEvent.wheel(screen.getByRole('listitem'), { deltaX: 80, deltaY: 0 });
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByText('Delete this meeting?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    view.rerender(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={meeting.id} />);
    const deleteButton = screen.getByRole('button', { name: 'Delete Stand Up' }) as HTMLButtonElement;
    expect(deleteButton.disabled).toBe(true);
    fireEvent.wheel(screen.getByRole('listitem'), { deltaX: 80, deltaY: 0 });
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('clears search from the embedded search control', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[]} selectedMeetingId={null} searchText="stand" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    await user.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(intents.setMeetingSearch).toHaveBeenCalledWith('');
    expect(screen.getByText('No matching meetings')).toBeInTheDocument();
  });

  it('shows analysis progress only on the active meeting row', () => {
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={meeting.id} />);

    expect(screen.getByText('Analyzing…')).toBeInTheDocument();
    expect(screen.queryByText('2 pending')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open latest analysis for Stand Up' })).toBeInTheDocument();
  });

  it('renders a backend full-text result even when its title does not match the query', () => {
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="participant-only-match" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    expect(screen.getByText('Stand Up')).toBeInTheDocument();
  });

  it('shows an explicit Load more button when another page is available and loads it on click', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore loadMoreError={null} activeAnalysisMeetingId={null} />);

    const loadMoreButton = screen.getByRole('button', { name: 'Load more meetings' });
    await user.click(loadMoreButton);

    expect(intents.loadMoreMeetings).toHaveBeenCalledTimes(1);
  });

  it('does not show a Load more button once there is no further page', () => {
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    expect(screen.queryByRole('button', { name: /Load more meetings/ })).toBeNull();
  });

  it('disables the Load more button and shows a busy label while a page is loading', () => {
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore hasMore loadMoreError={null} activeAnalysisMeetingId={null} />);

    const loadMoreButton = screen.getByRole('button', { name: 'Loading more meetings…' });
    expect(loadMoreButton).toBeDisabled();
    expect(loadMoreButton).toHaveAttribute('aria-busy', 'true');
  });

  it('offers a retry after a page append fails, and hides the Load more button while the error is visible', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore loadMoreError="Could not load more meetings." activeAnalysisMeetingId={null} />);

    expect(screen.queryByRole('button', { name: /Load more meetings/ })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(intents.loadMoreMeetings).toHaveBeenCalledTimes(1);
  });

  it('reveals filters and sends comma-separated transcript values with its AND mode', async () => {
    const user = userEvent.setup();
    render(<MeetingHistorySidebar history={[]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    const disclosure = screen.getByRole('button', { name: 'Show advanced filters' });
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');

    fireEvent.change(screen.getByRole('searchbox', { name: 'Transcript' }), { target: { value: 'opportunity,stage' } });

    expect(intents.setMeetingSearchFilters).toHaveBeenCalledWith({ ...filters, transcript: 'opportunity,stage' });
    expect(screen.getByRole('button', { name: 'Transcript: match all comma-separated values' })).toBeInTheDocument();
  });

  it('retains locally entered filters when a stale selection snapshot arrives', async () => {
    const user = userEvent.setup();
    const view = render(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={null} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    await user.click(screen.getByRole('button', { name: 'Show advanced filters' }));
    fireEvent.change(screen.getByRole('searchbox', { name: 'Transcript' }), { target: { value: 'opportunity,stage' } });

    // Selecting a row can republish an older native UI snapshot before the
    // preceding filter intent has made its round trip through the bridge.
    view.rerender(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={meeting.id} searchText="" searchFilters={filters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    expect(screen.getByRole('searchbox', { name: 'Transcript' })).toHaveValue('opportunity,stage');

    const acknowledgedFilters = { ...filters, transcript: 'opportunity,stage' };
    view.rerender(<MeetingHistorySidebar history={[meeting]} selectedMeetingId={meeting.id} searchText="" searchFilters={acknowledgedFilters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);
    expect(screen.getByRole('searchbox', { name: 'Transcript' })).toHaveValue('opportunity,stage');
  });

  it('toggles a text field to OR and clears only advanced filters', async () => {
    const user = userEvent.setup();
    const activeFilters = { ...filters, queryMode: 'or' as const, participants: 'Miriam', processing: 'complete' as const };
    render(<MeetingHistorySidebar history={[]} selectedMeetingId={null} searchText="opportunity" searchFilters={activeFilters} isLoading={false} isLoadingMore={false} hasMore={false} loadMoreError={null} activeAnalysisMeetingId={null} />);

    await user.click(screen.getByRole('button', { name: 'Show advanced filters' }));
    await user.click(screen.getByRole('button', { name: 'Participants: match all comma-separated values' }));
    expect(intents.setMeetingSearchFilters).toHaveBeenCalledWith({ ...activeFilters, participantsMode: 'or' });

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(intents.setMeetingSearchFilters).toHaveBeenLastCalledWith({ ...filters, queryMode: 'or' });
    expect(screen.getByRole('searchbox', { name: 'Search meetings' })).toHaveValue('opportunity');
  });
});
