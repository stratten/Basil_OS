import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

const cloud = vi.hoisted(() => ({ ports: [] as number[] }));
vi.mock('../cloud/CloudTranscription', () => ({
  default: ({ port }: { port: number }) => {
    cloud.ports.push(port);
    return <div data-testid="cloud-transcription" />;
  },
}));
vi.mock('../resources/ResourceAdvice', () => ({ default: () => null }));
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
  isRecording: false,
  isViewingPastMeeting: false,
  transcriptionState: 'idle',
  connectionState: 'idle',
  statusMessage: 'Ready',
  recordingTimeString: '0:00',
  enableMicrophone: true,
  systemAudioCaptureMode: 'globalOutput',
  isCapturePaused: false,
  isLiveTranscriptionEnabled: true,
  companionApiPort: 8123,
} as unknown as MeetingUIStateDTO;

describe('RecordingControls cloud transcription', () => {
  it.each([
    ['idle', base],
    ['recording', { ...base, isRecording: true }],
    ['viewing a past meeting', { ...base, isViewingPastMeeting: true }],
  ])('mounts the control with the backend port while %s', (_label, ui) => {
    cloud.ports.length = 0;
    render(<RecordingControls ui={ui as MeetingUIStateDTO} />);
    expect(screen.getByTestId('cloud-transcription')).toBeInTheDocument();
    expect(cloud.ports[cloud.ports.length - 1]).toBe(8123);
  });

  it('passes port zero when the backend port is unknown', () => {
    cloud.ports.length = 0;
    render(<RecordingControls ui={{ ...base, companionApiPort: undefined }} />);
    expect(cloud.ports[cloud.ports.length - 1]).toBe(0);
  });
});
