import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import AudioSourceControls from './AudioSourceControls';

const setAudioSource = vi.hoisted(() => vi.fn());
vi.mock('../bridge/meetingBridge', () => ({ setAudioSource }));

const ui = {
  isRecording: false,
  isViewingPastMeeting: false,
  enableMicrophone: true,
  isSystemAudioAvailable: true,
  systemAudioCaptureMode: 'globalOutput',
  selectedAudioProcessId: null,
  availableAudioProcesses: [{
    id: 'apps',
    title: 'Apps',
    processes: [{
      id: 42,
      name: 'Zoom',
      kind: 'app',
      audioActive: true,
      bundleId: 'us.zoom.xos',
      iconDataUrl: 'data:image/png;base64,zoom-icon',
    }],
  }],
  microphoneInputRecoveryState: 'idle',
  microphoneInputRecoveryMessage: null,
} as MeetingUIStateDTO;

describe('AudioSourceControls', () => {
  beforeEach(() => setAudioSource.mockReset());

  it('uses switch semantics and an icon-capable grouped audio-source menu', async () => {
    const user = userEvent.setup();
    render(<AudioSourceControls ui={ui} />);
    const microphone = screen.getByRole('checkbox', { name: 'Microphone' });
    expect(microphone).toBeChecked();
    await user.click(microphone);
    expect(setAudioSource).toHaveBeenCalledWith({ enableMicrophone: false });

    const picker = screen.getByRole('combobox', { name: 'Audio Source' });
    expect(picker).toHaveAttribute('aria-expanded', 'false');
    await user.click(picker);
    expect(picker).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('group', { name: 'Apps' })).toBeInTheDocument();
    const zoomOption = screen.getByRole('option', { name: /Zoom/ });
    expect(zoomOption.querySelector('img')).toHaveAttribute('src', 'data:image/png;base64,zoom-icon');
    await user.click(zoomOption);
    expect(setAudioSource).toHaveBeenCalledWith({ captureMode: 'selectedProcess', processId: 42 });
    expect(picker).toHaveAttribute('aria-expanded', 'false');
  });

  it('disables source controls for a past meeting', () => {
    render(<AudioSourceControls ui={{ ...ui, isViewingPastMeeting: true }} />);
    expect(screen.getByRole('checkbox', { name: 'Microphone' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Audio Source' })).toBeDisabled();
  });

  describe('Microphone notices', () => {
    it('shows nothing while the microphone is healthy', () => {
      render(<AudioSourceControls ui={ui} />);
      expect(screen.queryByRole('alert')).toBeNull();
    });

    it('shows a warning with its explanation while the microphone is only delivering silence', () => {
      const { container } = render(
        <AudioSourceControls
          ui={{
            ...ui,
            isRecording: true,
            microphoneInputRecoveryState: 'silent',
            microphoneInputRecoveryMessage: 'Your microphone is only delivering silence. Another app, such as a call, may be using it.',
          }}
        />,
      );
      expect(screen.getByRole('alert')).toHaveTextContent('Your microphone is only delivering silence. Another app, such as a call, may be using it.');
      expect(container.querySelector('.meeting-audio-recovery-notice--silent')).not.toBeNull();
      expect(container.querySelector('.meeting-audio-recovery-notice-icon')).toHaveAttribute('aria-hidden', 'true');
    });

    it('falls back to the standard explanation when the silent state arrives without a message', () => {
      render(<AudioSourceControls ui={{ ...ui, microphoneInputRecoveryState: 'silent', microphoneInputRecoveryMessage: null }} />);
      expect(screen.getByRole('alert')).toHaveTextContent('Your microphone is only delivering silence.');
    });

    it('keeps the existing reconnecting and failed notices unchanged and without the silent styling', () => {
      const { container, rerender } = render(
        <AudioSourceControls ui={{ ...ui, microphoneInputRecoveryState: 'reconnecting' }} />,
      );
      expect(screen.getByRole('alert')).toHaveTextContent('Reconnecting to the microphone…');
      expect(container.querySelector('.meeting-audio-recovery-notice--silent')).toBeNull();

      rerender(
        <AudioSourceControls
          ui={{ ...ui, microphoneInputRecoveryState: 'failed', microphoneInputRecoveryMessage: 'The microphone stopped delivering audio.' }}
        />,
      );
      expect(screen.getByRole('alert')).toHaveTextContent('The microphone stopped delivering audio.');
      expect(container.querySelector('.meeting-audio-recovery-notice--silent')).toBeNull();
      expect(container.querySelector('.meeting-audio-recovery-notice-icon')).toBeNull();
    });
  });

  describe('Companion switch', () => {
    const companion = { enabled: false, busy: false, paneHidden: true, onChange: vi.fn(), onShowPane: vi.fn(), error: null, onDismissError: vi.fn() };

    it('sits right after the audio source picker and responds even when the source controls are locked by a recording', async () => {
      const user = userEvent.setup();
      companion.onChange.mockReset();
      const { container } = render(<AudioSourceControls ui={{ ...ui, isRecording: true }} companion={companion} />);
      expect(screen.getByRole('combobox', { name: 'Audio Source' })).toBeDisabled();
      const toggle = screen.getByRole('checkbox', { name: 'Companion' });
      expect(toggle).toBeEnabled();
      const pickerBlock = container.querySelector('.meeting-system-audio-picker') as HTMLElement;
      expect(pickerBlock.nextElementSibling).toBe(container.querySelector('.companion-toggle'));
      await user.click(toggle);
      expect(companion.onChange).toHaveBeenCalledWith(true);
    });

    it('is offered before any recording and when system audio is unavailable', () => {
      render(<AudioSourceControls ui={{ ...ui, isSystemAudioAvailable: false }} companion={companion} />);
      expect(screen.getByRole('checkbox', { name: 'Companion' })).toBeEnabled();
    });

    it('is absent without Companion props, and is disabled only while busy', () => {
      const { rerender } = render(<AudioSourceControls ui={ui} />);
      expect(screen.queryByRole('checkbox', { name: 'Companion' })).toBeNull();
      rerender(<AudioSourceControls ui={ui} companion={{ ...companion, busy: true }} />);
      expect(screen.getByRole('checkbox', { name: 'Companion' })).toBeDisabled();
    });

    it('reports a failed switch action beside the switch with a dismiss action', async () => {
      const user = userEvent.setup();
      const onDismissError = vi.fn();
      render(<AudioSourceControls ui={ui} companion={{ ...companion, error: 'Companion enable failed (500)', onDismissError }} />);
      expect(screen.getByRole('alert')).toHaveTextContent('Companion enable failed (500)');
      await user.click(screen.getByRole('button', { name: 'Dismiss' }));
      expect(onDismissError).toHaveBeenCalledTimes(1);
    });
  });
});
