import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { MeetingListItemDTO } from '../bridge/types';
import MeetingHistorySidebar from './MeetingHistorySidebar';

vi.mock('../bridge/meetingBridge', () => ({
  deleteMeeting: vi.fn(),
  loadMoreMeetings: vi.fn(),
  selectMeeting: vi.fn(),
  setMeetingSearch: vi.fn(),
  setMeetingSearchFilters: vi.fn(),
  setSidebarCollapsed: vi.fn(),
  startNewMeeting: vi.fn(),
  viewAnalysis: vi.fn(),
}));

const meeting: MeetingListItemDTO = {
  id: 'meeting-1',
  name: 'Stand Up',
  purpose: null,
  participants: [],
  startTime: '2026-08-14T15:02:00Z',
  endTime: null,
  durationSeconds: 2940,
  isPostProcessed: true,
  analysisSummary: null,
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

function renderSidebar(history: MeetingListItemDTO[], isLoading: boolean, hasMore = false) {
  return render(
    <MeetingHistorySidebar
      history={history}
      selectedMeetingId={null}
      searchText=""
      searchFilters={filters}
      isLoading={isLoading}
      isLoadingMore={false}
      hasMore={hasMore}
      loadMoreError={null}
      activeAnalysisMeetingId={null}
    />,
  );
}

describe('MeetingHistorySidebar refresh continuity', () => {
  it('keeps meetings visible and marks the list busy while history reloads', () => {
    const { container } = renderSidebar([meeting], true, true);
    expect(screen.queryByText('Loading meetings…')).not.toBeInTheDocument();
    expect(screen.getByText('Stand Up')).toBeInTheDocument();
    expect(container.querySelector('.meeting-history-list')?.getAttribute('aria-busy')).toBe('true');
    expect(screen.getByRole('button', { name: 'Load more meetings' })).toBeDisabled();
  });

  it('shows the loading row only when no meetings are visible', () => {
    renderSidebar([], true);
    expect(screen.getByText('Loading meetings…')).toBeInTheDocument();
  });

  it('opens and closes advanced filters through a presence region', async () => {
    const user = userEvent.setup();
    const { container } = renderSidebar([meeting], false);
    await user.click(screen.getByRole('button', { name: 'Show advanced filters' }));
    expect(container.querySelector('#meeting-advanced-filters')?.parentElement?.hasAttribute('data-presence-phase')).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Show advanced filters' }));
    expect(container.querySelector('#meeting-advanced-filters')).toBeNull();
  });
});
