import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MeetingsTab from './MeetingsTab';
import { enqueueBoardMeetingsAvailabilityChanged } from '../services/bridge';

const mocks = vi.hoisted(() => ({
  activateBoardMeetingsSurface: vi.fn(),
  deactivateBoardMeetingsSurface: vi.fn(),
  postMessage: vi.fn(),
}));

vi.mock('../services/bridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/bridge')>();
  return {
    ...actual,
    activateBoardMeetingsSurface: mocks.activateBoardMeetingsSurface,
    deactivateBoardMeetingsSurface: mocks.deactivateBoardMeetingsSurface,
    postBridgeMessage: mocks.postMessage,
  };
});

describe('MeetingsTab', () => {
  it('activates the Board Meetings surface on mount and deactivates on unmount', () => {
    const { unmount } = render(<MeetingsTab />);
    expect(mocks.activateBoardMeetingsSurface).toHaveBeenCalledTimes(1);
    expect(mocks.deactivateBoardMeetingsSurface).not.toHaveBeenCalled();

    unmount();
    expect(mocks.deactivateBoardMeetingsSurface).toHaveBeenCalledTimes(1);
  });

  it('renders the embedded spacer when availability is embedded', () => {
    render(<MeetingsTab />);
    expect(document.querySelector('.meetings-embedded-spacer')).toBeTruthy();
  });

  it('shows the separate-window message when the standalone window is authoritative', () => {
    render(<MeetingsTab />);

    act(() => {
      enqueueBoardMeetingsAvailabilityChanged({ availability: 'separate_window' });
    });

    expect(screen.getByText('Meeting Assistant is open in a separate window.')).toBeTruthy();
  });

  it('returns to the embedded spacer when availability changes back to embedded', () => {
    render(<MeetingsTab />);

    act(() => {
      enqueueBoardMeetingsAvailabilityChanged({ availability: 'separate_window' });
    });
    act(() => {
      enqueueBoardMeetingsAvailabilityChanged({ availability: 'embedded' });
    });

    expect(document.querySelector('.meetings-embedded-spacer')).toBeTruthy();
  });
});
