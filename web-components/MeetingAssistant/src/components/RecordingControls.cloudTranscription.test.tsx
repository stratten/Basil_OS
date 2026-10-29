import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';

import userEvent from '@testing-library/user-event';
import * as bridge from '../bridge/meetingBridge';
import { cloudState } from '../cloud/cloudTestFixtures';
import type { CloudTranscriptionState } from '../cloud/cloudTranscriptionTypes';

const cloud = vi.hoisted(() => ({
  ports: [] as number[],
  state: null as CloudTranscriptionState | null,
  update: vi.fn(),
}));
vi.mock('../cloud/useCloudTranscription', () => ({
  useCloudTranscription: (port: number) => {
    cloud.ports.push(port);
    return { state: cloud.state, busy: false, actionError: null, update: cloud.update };
  },
}));
vi.mock('../cloud/CloudTranscription', () => ({
  default: ({ state }: { state: CloudTranscriptionState | null }) => <div data-testid="cloud-transcription" data-has-state={state !== null} />,
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
  setLiveEngine: vi.fn(),
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
  selectedModel: 'parakeet',
  availableModels: [{ id: 'parakeet', name: 'p', displayName: 'Parakeet', provider: null, category: 'local' }],
} as unknown as MeetingUIStateDTO;

const configured = () => cloudState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] });

beforeEach(() => {
  cloud.ports.length = 0;
  cloud.state = null;
  vi.mocked(bridge.setLiveEngine).mockClear();
  cloud.update.mockReset();
});

describe('RecordingControls cloud transcription', () => {
  it.each([
    ['idle', base],
    ['recording', { ...base, isRecording: true }],
    ['viewing a past meeting', { ...base, isViewingPastMeeting: true }],
  ])('mounts the chip with the backend port while %s', (_label, ui) => {
    cloud.state = cloudState();
    render(<RecordingControls ui={ui as MeetingUIStateDTO} />);
    expect(screen.getByTestId('cloud-transcription')).toHaveAttribute('data-has-state', 'true');
    expect(cloud.ports[cloud.ports.length - 1]).toBe(8123);
  });

  it('passes port zero when the backend port is unknown', () => {
    render(<RecordingControls ui={{ ...base, companionApiPort: undefined }} />);
    expect(cloud.ports[cloud.ports.length - 1]).toBe(0);
  });
});

describe('RecordingControls idle layout and live model selector', () => {
  it('puts the status on the right of the idle row, after the controls', () => {
    const { container } = render(<RecordingControls ui={base} />);
    const row = container.querySelector('.meeting-idle-row') as HTMLElement;
    expect(row.children[0]).toHaveClass('meeting-idle-controls');
    expect(row.children[1]).toHaveClass('meeting-status-row');
    expect(within(row.children[0] as HTMLElement).getByRole('button', { name: /Start/ })).toBeInTheDocument();
  });

  it('names Whisper Base as the local live model whatever transcription model is selected', () => {
    render(<RecordingControls ui={base} />);
    const trigger = screen.getByRole('button', { name: 'Live transcription model' });
    expect(trigger).toHaveTextContent('Whisper Base');
  });

  it('lists the cloud services the user set up and applies the choice to this recording only', async () => {
    cloud.state = configured();
    render(<RecordingControls ui={base} />);
    await userEvent.click(screen.getByRole('button', { name: 'Live transcription model' }));
    const options = screen.getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual(['Whisper Base', 'Deepgram']);
    await userEvent.click(screen.getByRole('option', { name: 'Deepgram' }));
    expect(bridge.setLiveEngine).toHaveBeenCalledWith('deepgram');
    expect(cloud.update).not.toHaveBeenCalled();
  });

  it('starts on the saved default and returns to it without sending a deviation', async () => {
    cloud.state = { ...configured(), enabled: true };
    render(<RecordingControls ui={base} />);
    expect(screen.getByRole('button', { name: 'Live transcription model' })).toHaveTextContent('Deepgram');
    await userEvent.click(screen.getByRole('button', { name: 'Live transcription model' }));
    await userEvent.click(screen.getByRole('option', { name: 'Whisper Base' }));
    expect(bridge.setLiveEngine).toHaveBeenLastCalledWith('local');
    expect(cloud.update).not.toHaveBeenCalled();
  });

  it('shows this recording\'s choice over the saved default and sends null when the default is picked again', async () => {
    cloud.state = { ...configured(), enabled: true };
    render(<RecordingControls ui={{ ...base, liveEngineOverride: 'local' }} />);
    expect(screen.getByRole('button', { name: 'Live transcription model' })).toHaveTextContent('Whisper Base');
    await userEvent.click(screen.getByRole('button', { name: 'Live transcription model' }));
    await userEvent.click(screen.getByRole('option', { name: 'Deepgram' }));
    expect(bridge.setLiveEngine).toHaveBeenLastCalledWith(null);
  });

  it.each([
    ['Live Transcribe is off', { ...base, isLiveTranscriptionEnabled: false }],
    ['recording', { ...base, isRecording: true }],
    ['viewing a past meeting', { ...base, isViewingPastMeeting: true }],
  ])('hides the selector when %s', (_label, ui) => {
    cloud.state = configured();
    render(<RecordingControls ui={ui as MeetingUIStateDTO} />);
    expect(screen.queryByRole('button', { name: 'Live transcription model' })).toBeNull();
  });
});
