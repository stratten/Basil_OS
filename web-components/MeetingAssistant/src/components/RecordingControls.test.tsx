import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import RecordingControls from './RecordingControls';

const bridge = vi.hoisted(() => ({
  resumeMeeting: vi.fn(),
  startNewMeeting: vi.fn(),
  toggleRecording: vi.fn(),
  pauseRecording: vi.fn(),
  resumeRecording: vi.fn(),
  cancelRecording: vi.fn(),
  setLiveTranscription: vi.fn(),
}));
vi.mock('../bridge/meetingBridge', () => bridge);
vi.mock('../bridge/meetingMeterStore', () => ({
  useMeetingMeter: () => ({ microphoneAudioLevel: 0.4, systemAudioLevel: 0.7 }),
}));

const ui = {
  isRecording: false,
  isViewingPastMeeting: false,
  transcriptionState: 'idle',
  connectionState: 'ready',
  statusMessage: 'Ready to start transcription',
  recordingTimeString: '0:00',
  enableMicrophone: true,
  systemAudioCaptureMode: 'globalOutput',
  isCapturePaused: false,
  isLiveTranscriptionEnabled: true,
} as MeetingUIStateDTO;

const recordingUi = { ...ui, isRecording: true, transcriptionState: 'listening', connectionState: 'recording' } as MeetingUIStateDTO;

describe('RecordingControls', () => {
  beforeEach(() => {
    Object.values(bridge).forEach((mock) => mock.mockClear());
  });

  it('places idle readiness above Start and omits literal idle state', () => {
    const { container } = render(<RecordingControls ui={ui} />);
    const status = screen.getByText('Ready to start transcription');
    const start = screen.getByRole('button', { name: 'Start' });
    expect(status.compareDocumentPosition(start) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container).not.toHaveTextContent(/\bidle\b/i);
  });

  it('renders icon-bearing past-meeting actions', () => {
    render(<RecordingControls ui={{ ...ui, isViewingPastMeeting: true }} />);
    expect(screen.getByRole('button', { name: 'Resume' }).querySelector('svg')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Start New' }).querySelector('svg')).not.toBeNull();
  });

  it('labels actions without the word Meeting', () => {
    const idle = render(<RecordingControls ui={ui} />);
    expect(idle.container.querySelectorAll('button')).not.toHaveLength(0);
    idle.container.querySelectorAll('button').forEach((button) => expect(button).not.toHaveTextContent(/meeting/i));
    idle.unmount();
    const past = render(<RecordingControls ui={{ ...ui, isViewingPastMeeting: true }} />);
    past.container.querySelectorAll('button').forEach((button) => expect(button).not.toHaveTextContent(/meeting/i));
    past.unmount();
    const recording = render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    recording.container.querySelectorAll('button').forEach((button) => expect(button).not.toHaveTextContent(/meeting/i));
    expect(screen.getByRole('alertdialog')).not.toHaveTextContent(/meeting/i);
  });

  it('shows the paused status dot instead of the recording red', () => {
    const { container } = render(<RecordingControls ui={{ ...recordingUi, isCapturePaused: true }} />);
    expect(container.querySelector('.meeting-connection-indicator--paused')).not.toBeNull();
    expect(container.querySelector('.meeting-connection-indicator--recording')).toBeNull();
  });

  it('renders active recording timer and source meters', () => {
    render(<RecordingControls ui={{ ...ui, isRecording: true, transcriptionState: 'listening', recordingTimeString: '3:21' }} />);
    expect(screen.getByRole('button', { name: 'End' })).toBeInTheDocument();
    expect(screen.getByText('3:21')).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'Microphone level' })).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'System Audio level' })).toBeInTheDocument();
  });

  it('pauses an active recording without ending it', () => {
    render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(bridge.pauseRecording).toHaveBeenCalledTimes(1);
    expect(bridge.toggleRecording).not.toHaveBeenCalled();
  });

  it('disables Pause until capture is connected', () => {
    render(<RecordingControls ui={{ ...recordingUi, connectionState: 'connecting' }} />);
    expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled();
  });

  it('offers Resume, End, and Cancel while paused', () => {
    render(<RecordingControls ui={{ ...recordingUi, isCapturePaused: true }} />);
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    expect(bridge.resumeRecording).toHaveBeenCalledTimes(1);
  });

  it('requires confirmation before discarding the recording', () => {
    render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(bridge.cancelRecording).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Discard this recording?');
    fireEvent.click(screen.getByRole('button', { name: 'Discard Recording' }));
    expect(bridge.cancelRecording).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('keeps recording when the discard confirmation is dismissed', () => {
    render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep Recording' }));
    expect(bridge.cancelRecording).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
  });

  it('focuses Keep Recording and dismisses the discard confirmation with Escape', () => {
    render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Keep Recording' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(bridge.cancelRecording).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  });

  it('closes a pending discard confirmation when recording ends', () => {
    const { rerender } = render(<RecordingControls ui={recordingUi} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    rerender(<RecordingControls ui={ui} />);
    rerender(<RecordingControls ui={recordingUi} />);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('toggles live transcription mid-recording without stopping capture', () => {
    render(<RecordingControls ui={recordingUi} />);
    const toggle = screen.getByRole('checkbox', { name: 'Live Transcribe' });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(bridge.setLiveTranscription).toHaveBeenCalledWith(false);
    expect(bridge.toggleRecording).not.toHaveBeenCalled();
  });

  it('lets the user choose record-only before starting', () => {
    render(<RecordingControls ui={{ ...ui, isLiveTranscriptionEnabled: false }} />);
    const toggle = screen.getByRole('checkbox', { name: 'Live Transcribe' });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(bridge.setLiveTranscription).toHaveBeenCalledWith(true);
  });
});
