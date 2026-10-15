import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

const advice = vi.hoisted(() => ({ props: [] as unknown[] }));
vi.mock('../resources/ResourceAdvice', () => ({
  default: (props: unknown) => {
    advice.props.push(props);
    return <div data-testid="resource-advice" />;
  },
}));
vi.mock('../bridge/meetingBridge', () => ({
  resumeMeeting: vi.fn(),
  startNewMeeting: vi.fn(),
  toggleRecording: vi.fn(),
  pauseRecording: vi.fn(),
  resumeRecording: vi.fn(),
  cancelRecording: vi.fn(),
  setLiveTranscription: vi.fn(),
}));
vi.mock('../bridge/meetingMeterStore', () => ({ useMeetingMeter: () => ({ microphoneAudioLevel: 0, systemAudioLevel: 0 }) }));

import RecordingControls from './RecordingControls';

const base = {
  isRecording: true,
  isViewingPastMeeting: false,
  transcriptionState: 'listening',
  connectionState: 'recording',
  statusMessage: 'Recording',
  recordingTimeString: '0:10',
  enableMicrophone: true,
  systemAudioCaptureMode: 'globalOutput',
  isCapturePaused: false,
  isLiveTranscriptionEnabled: true,
  companionApiPort: 8123,
  thermalState: 'serious',
} as MeetingUIStateDTO;

describe('RecordingControls resource advice', () => {
  it('mounts the advice with the backend port and thermal state while recording', () => {
    advice.props.length = 0;
    render(<RecordingControls ui={base} />);
    expect(screen.getByTestId('resource-advice')).toBeInTheDocument();
    expect(advice.props[advice.props.length - 1]).toEqual({ port: 8123, recording: true, thermalState: 'serious' });
  });

  it('does not mount it when idle or viewing a past meeting', () => {
    render(<RecordingControls ui={{ ...base, isRecording: false }} />);
    render(<RecordingControls ui={{ ...base, isRecording: false, isViewingPastMeeting: true }} />);
    expect(screen.queryByTestId('resource-advice')).toBeNull();
  });

  it('treats an unavailable port as port zero', () => {
    advice.props.length = 0;
    render(<RecordingControls ui={{ ...base, companionApiPort: undefined, thermalState: undefined }} />);
    expect(advice.props[advice.props.length - 1]).toEqual({ port: 0, recording: true, thermalState: undefined });
  });
});
