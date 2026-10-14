import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import CollapsedRecordingActions from './CollapsedRecordingActions';
import { pauseRecording, resumeRecording, toggleRecording } from '../bridge/meetingBridge';

vi.mock('../bridge/meetingBridge', () => ({
  pauseRecording: vi.fn(),
  resumeRecording: vi.fn(),
  toggleRecording: vi.fn(),
  cancelRecording: vi.fn(),
  resumeMeeting: vi.fn(),
  startNewMeeting: vi.fn(),
  setLiveTranscription: vi.fn(),
}));

const recordingUi = {
  isRecording: true,
  isCapturePaused: false,
  connectionState: 'recording',
  transcriptionState: 'listening',
} as MeetingUIStateDTO;

describe('CollapsedRecordingActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('pauses and ends the recording from the collapsed header', () => {
    render(<CollapsedRecordingActions ui={recordingUi} />);

    fireEvent.click(screen.getByRole('button', { name: 'Pause recording' }));
    expect(pauseRecording).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Resume recording' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'End recording' }));
    expect(toggleRecording).toHaveBeenCalledTimes(1);
  });

  it('offers Resume instead of Pause while capture is paused', () => {
    render(<CollapsedRecordingActions ui={{ ...recordingUi, isCapturePaused: true }} />);

    expect(screen.queryByRole('button', { name: 'Pause recording' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Resume recording' }));
    expect(resumeRecording).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'End recording' })).toBeEnabled();
  });

  it('keeps Pause disabled until the connection is recording, like the expanded controls', () => {
    render(<CollapsedRecordingActions ui={{ ...recordingUi, connectionState: 'connecting' }} />);

    const pause = screen.getByRole('button', { name: 'Pause recording' });
    expect(pause).toBeDisabled();
    fireEvent.click(pause);
    expect(pauseRecording).not.toHaveBeenCalled();
  });

  it('disables End while models are loading', () => {
    render(<CollapsedRecordingActions ui={{ ...recordingUi, transcriptionState: 'loadingModels' }} />);

    const end = screen.getByRole('button', { name: 'End recording' });
    expect(end).toBeDisabled();
    fireEvent.click(end);
    expect(toggleRecording).not.toHaveBeenCalled();
  });
});
