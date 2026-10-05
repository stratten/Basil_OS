import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FullWidget } from './FullWidget';
import { initialTranscriptionState } from '../state/transcriptionReducer';
import * as bridge from '../bridge/transcriptionWidgetBridge';

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  clearTranscription: vi.fn(),
  closeWidget: vi.fn(),
  openSystemMicrophoneSettings: vi.fn(),
  toggleMinimizedState: vi.fn(),
  toggleRecording: vi.fn(),
  selectTranscriptionModel: vi.fn(),
  showTranscriptionError: vi.fn(),
}));

describe('FullWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the disconnected message when isConnected is false', () => {
    render(<FullWidget state={{ ...initialTranscriptionState, isConnected: false }} />);
    expect(screen.getByText('Disconnected from server')).toBeInTheDocument();
  });

  it('renders a clickable System Settings link for the mic-permission error', async () => {
    const state = { ...initialTranscriptionState, error: 'Microphone access denied. Click here to open System Settings to grant access.' };
    render(<FullWidget state={state} />);
    const link = screen.getByRole('button', { name: /click here to open system settings/i });
    await userEvent.click(link);
    expect(bridge.openSystemMicrophoneSettings).toHaveBeenCalledOnce();
  });

  it('renders a plain error message for non-permission errors', () => {
    const state = { ...initialTranscriptionState, error: 'Connection lost' };
    render(<FullWidget state={state} />);
    expect(screen.getByText('Connection lost')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /connection lost/i })).not.toBeInTheDocument();
  });

  it('disables Clear for a status message and enables it for real transcript', () => {
    const { rerender } = render(<FullWidget state={{ ...initialTranscriptionState, transcriptionText: 'Ready to record' }} />);
    expect(screen.getByRole('button', { name: /clear/i })).toBeDisabled();
    rerender(<FullWidget state={{ ...initialTranscriptionState, transcriptionText: 'hello world' }} />);
    expect(screen.getByRole('button', { name: /clear/i })).toBeEnabled();
  });

  it('shows the timer only while recording', () => {
    const { rerender } = render(<FullWidget state={{ ...initialTranscriptionState, isRecording: false, elapsedSeconds: 12 }} />);
    expect(screen.queryByText('0:12')).not.toBeInTheDocument();
    rerender(<FullWidget state={{ ...initialTranscriptionState, isRecording: true, elapsedSeconds: 12 }} />);
    expect(screen.getByText('0:12')).toBeInTheDocument();
  });

  it('delegates recording cancellation and closing to the single native close intent', async () => {
    render(<FullWidget state={{ ...initialTranscriptionState, isRecording: true }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(bridge.closeWidget).toHaveBeenCalledOnce();
  });

  it('renders the hotkey badge on the record button when present', () => {
    render(<FullWidget state={{ ...initialTranscriptionState, hotkeyDisplayString: '⌥⇧D' }} />);
    expect(screen.getByText('(⌥⇧D)')).toBeInTheDocument();
  });
});
