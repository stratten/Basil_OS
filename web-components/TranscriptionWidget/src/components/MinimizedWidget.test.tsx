import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MinimizedWidget } from './MinimizedWidget';
import { initialTranscriptionState } from '../state/transcriptionReducer';
import * as bridge from '../bridge/transcriptionWidgetBridge';

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  closeWidget: vi.fn(),
  toggleMinimizedState: vi.fn(),
  toggleRecording: vi.fn(),
  selectTranscriptionModel: vi.fn(),
  showTranscriptionError: vi.fn(),
}));

describe('MinimizedWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('disables the record button while canToggleRecording is false', () => {
    const state = { ...initialTranscriptionState, canToggleRecording: false };
    render(<MinimizedWidget state={state} />);
    expect(screen.getByTitle('Start recording')).toBeDisabled();
  });

  it('delegates recording cancellation and closing to the single native close intent', async () => {
    const state = { ...initialTranscriptionState, isRecording: true, canToggleRecording: true };
    render(<MinimizedWidget state={state} />);
    await userEvent.click(screen.getByTitle('Cancel recording and close'));
    expect(bridge.closeWidget).toHaveBeenCalledOnce();
  });

  it('uses the same native close intent when idle', async () => {
    const state = { ...initialTranscriptionState, isRecording: false, isStartingRecording: false };
    render(<MinimizedWidget state={state} />);
    await userEvent.click(screen.getByTitle('Close widget'));
    expect(bridge.closeWidget).toHaveBeenCalledOnce();
  });

  it('renders the error badge only when an error is present', () => {
    const { rerender } = render(<MinimizedWidget state={{ ...initialTranscriptionState, error: null }} />);
    expect(screen.queryByRole('button', { name: /transcription failed/i })).not.toBeInTheDocument();
    rerender(<MinimizedWidget state={{ ...initialTranscriptionState, error: 'boom' }} />);
    expect(screen.getByRole('button', { name: /transcription failed/i })).toBeInTheDocument();
  });

  it('toggles minimized state via the expand button', async () => {
    render(<MinimizedWidget state={initialTranscriptionState} />);
    await userEvent.click(screen.getByRole('button', { name: 'Expand widget' }));
    expect(bridge.toggleMinimizedState).toHaveBeenCalledOnce();
  });

  it('reveals the mini model picker only while the native drag region is hovered', () => {
    const { container } = render(<MinimizedWidget state={initialTranscriptionState} />);
    const picker = container.querySelector('.transcription-widget__mini-picker');

    expect(picker).toHaveStyle({ opacity: '0', pointerEvents: 'none' });
    fireEvent(window, new CustomEvent('basilTranscriptionNativeHover', { detail: true }));
    expect(picker).toHaveStyle({ opacity: '0.72', pointerEvents: 'auto' });
    fireEvent(window, new CustomEvent('basilTranscriptionNativeHover', { detail: false }));
    expect(picker).toHaveStyle({ opacity: '0', pointerEvents: 'none' });
  });
});
