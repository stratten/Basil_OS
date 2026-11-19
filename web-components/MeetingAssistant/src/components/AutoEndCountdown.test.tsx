import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import AutoEndCountdown from './AutoEndCountdown';
import RecordingControls from './RecordingControls';

const bridge = vi.hoisted(() => ({
  resumeMeeting: vi.fn(),
  startNewMeeting: vi.fn(),
  toggleRecording: vi.fn(),
  pauseRecording: vi.fn(),
  resumeRecording: vi.fn(),
  cancelRecording: vi.fn(),
  dismissAutoEnd: vi.fn(),
  setLiveTranscription: vi.fn(),
  setLiveEngine: vi.fn(),
}));
vi.mock('../bridge/meetingBridge', () => bridge);
vi.mock('../bridge/meetingMeterStore', () => ({
  useMeetingMeter: () => ({ microphoneAudioLevel: 0.4, systemAudioLevel: 0.7 }),
}));

const START = 1_000_000;

function countdownEndingIn(seconds: number, totalSeconds = 30) {
  return { deadlineEpochMs: START + seconds * 1000, totalSeconds };
}

const recordingUi = {
  isRecording: true,
  isViewingPastMeeting: false,
  transcriptionState: 'listening',
  connectionState: 'recording',
  statusMessage: 'Recording',
  recordingTimeString: '3:21',
  enableMicrophone: true,
  systemAudioCaptureMode: 'globalOutput',
  isCapturePaused: false,
  isLiveTranscriptionEnabled: true,
} as MeetingUIStateDTO;

describe('AutoEndCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
    Object.values(bridge).forEach((mock) => mock.mockClear());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the seconds left and a bar scaled to the share of the countdown that remains', () => {
    render(<AutoEndCountdown countdown={countdownEndingIn(15)} />);

    expect(screen.getByRole('timer')).toHaveTextContent('Ending in 15s');
    const bar = screen.getByRole('progressbar', { name: 'Time until this recording ends' });
    expect(bar).toHaveAttribute('aria-valuenow', '15');
    expect(bar).toHaveAttribute('aria-valuemax', '30');
    expect(bar.querySelector<HTMLElement>('.meeting-auto-end-bar-fill')?.style.transform).toBe('scaleX(0.5)');
  });

  it('counts down as time passes and says Ending now at zero', () => {
    render(<AutoEndCountdown countdown={countdownEndingIn(3)} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent('Ending in 2s');

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent('Ending now');
    expect(screen.getByRole('progressbar').querySelector<HTMLElement>('.meeting-auto-end-bar-fill')?.style.transform).toBe('scaleX(0)');
  });

  it('follows a replaced deadline', () => {
    const { rerender } = render(<AutoEndCountdown countdown={countdownEndingIn(5)} />);

    rerender(<AutoEndCountdown countdown={countdownEndingIn(25)} />);

    expect(screen.getByRole('timer')).toHaveTextContent('Ending in 25s');
  });

  it('never draws a bar fuller than the whole countdown when the deadline is further away than its length', () => {
    render(<AutoEndCountdown countdown={countdownEndingIn(90)} />);

    expect(screen.getByRole('progressbar').querySelector<HTMLElement>('.meeting-auto-end-bar-fill')?.style.transform).toBe('scaleX(1)');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '30');
  });

  it('hides itself when the stop never happened well after the deadline', () => {
    const { container } = render(<AutoEndCountdown countdown={countdownEndingIn(1)} />);

    act(() => {
      vi.advanceTimersByTime(22_000);
    });

    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the recording going when Keep Recording is pressed', () => {
    render(<AutoEndCountdown countdown={countdownEndingIn(10)} />);

    fireEvent.click(screen.getByRole('button', { name: 'Keep Recording' }));

    expect(bridge.dismissAutoEnd).toHaveBeenCalledTimes(1);
    expect(bridge.toggleRecording).not.toHaveBeenCalled();
  });

  it('still counts down a paused recording, offering Resume beside the countdown, because the automatic end stops a paused recording too', () => {
    const { container } = render(<RecordingControls ui={{ ...recordingUi, isCapturePaused: true, autoEndCountdown: countdownEndingIn(20) }} />);

    expect(screen.getByRole('timer')).toHaveTextContent('Ending in 20s');
    expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Keep Recording' }));
    expect(bridge.dismissAutoEnd).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.meeting-auto-end')).not.toBeNull();
  });

  it('appears below the recording buttons only while the host reports a countdown', () => {
    const { container, rerender } = render(<RecordingControls ui={recordingUi} />);
    expect(container.querySelector('.meeting-auto-end')).toBeNull();

    rerender(<RecordingControls ui={{ ...recordingUi, autoEndCountdown: countdownEndingIn(20) }} />);
    const countdown = container.querySelector('.meeting-auto-end');
    const row = container.querySelector('.meeting-active-recording-row');
    expect(countdown).not.toBeNull();
    expect(row && countdown && row.compareDocumentPosition(countdown) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    rerender(<RecordingControls ui={{ ...recordingUi, autoEndCountdown: null }} />);
    expect(container.querySelector('.meeting-auto-end')).toBeNull();
  });
});
