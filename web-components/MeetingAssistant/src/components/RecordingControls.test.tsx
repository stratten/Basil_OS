import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import RecordingControls from './RecordingControls';

vi.mock('../bridge/meetingBridge', () => ({ resumeMeeting: vi.fn(), startNewMeeting: vi.fn(), toggleRecording: vi.fn() }));
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
} as MeetingUIStateDTO;

describe('RecordingControls', () => {
  it('places idle readiness above Start Meeting and omits literal idle state', () => {
    const { container } = render(<RecordingControls ui={ui} />);
    const status = screen.getByText('Ready to start transcription');
    const start = screen.getByRole('button', { name: 'Start Meeting' });
    expect(status.compareDocumentPosition(start) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container).not.toHaveTextContent(/\bidle\b/i);
  });

  it('renders icon-bearing past-meeting actions', () => {
    render(<RecordingControls ui={{ ...ui, isViewingPastMeeting: true }} />);
    expect(screen.getByRole('button', { name: 'Resume Meeting' }).querySelector('svg')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Start New Meeting' }).querySelector('svg')).not.toBeNull();
  });

  it('renders active recording timer and source meters', () => {
    render(<RecordingControls ui={{ ...ui, isRecording: true, transcriptionState: 'listening', recordingTimeString: '3:21' }} />);
    expect(screen.getByRole('button', { name: 'End Meeting' })).toBeInTheDocument();
    expect(screen.getByText('3:21')).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'Microphone level' })).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'System Audio level' })).toBeInTheDocument();
  });
});
