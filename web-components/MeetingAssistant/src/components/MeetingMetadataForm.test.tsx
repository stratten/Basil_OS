import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MeetingMetadataForm from './MeetingMetadataForm';

const updateMetadata = vi.hoisted(() => vi.fn());
vi.mock('../bridge/meetingBridge', () => ({ updateMetadata }));

describe('MeetingMetadataForm', () => {
  beforeEach(() => {
    updateMetadata.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it('renders participant chips and serializes add/remove edits', async () => {
    render(<MeetingMetadataForm name="Stand Up" purpose="" participants="alex@example.com, Sam" isViewingPastMeeting={false} />);
    expect(screen.getByText('alex@example.com')).toBeInTheDocument();
    const draft = screen.getByPlaceholderText('Add participant');
    fireEvent.change(draft, { target: { value: 'Pat' } });
    fireEvent.keyDown(draft, { key: 'Enter' });
    act(() => vi.advanceTimersByTime(400));
    expect(updateMetadata).toHaveBeenCalledWith({ participants: 'alex@example.com, Sam, Pat' });
    fireEvent.click(screen.getByRole('button', { name: 'Remove Sam' }));
    act(() => vi.advanceTimersByTime(400));
    expect(updateMetadata).toHaveBeenCalledWith({ participants: 'alex@example.com, Pat' });
  });

  it('does not duplicate participants case-insensitively', async () => {
    render(<MeetingMetadataForm name="" purpose="" participants="Alex" isViewingPastMeeting={false} />);
    const draft = screen.getByPlaceholderText('Add participant');
    fireEvent.change(draft, { target: { value: 'alex' } });
    fireEvent.keyDown(draft, { key: 'Enter' });
    act(() => vi.advanceTimersByTime(400));
    expect(updateMetadata).not.toHaveBeenCalledWith({ participants: 'Alex, alex' });
  });

  it('keeps historical meeting metadata editable', () => {
    render(<MeetingMetadataForm name="Past" purpose="" participants="Alex" isViewingPastMeeting />);
    expect(screen.getByText('Viewing Past Meeting')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove Alex' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Add participant')).toBeInTheDocument();
  });
});
