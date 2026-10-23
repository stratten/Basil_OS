import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranscriptionModelPickerMenu } from './TranscriptionModelPickerMenu';
import { initialTranscriptionState } from '../state/transcriptionReducer';
import * as bridge from '../bridge/transcriptionWidgetBridge';

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  selectTranscriptionModel: vi.fn(),
  showTranscriptionModelMenu: vi.fn(),
}));

const models = [
  { id: 'local-1', displayName: 'Local Whisper', isApiModel: false },
  { id: 'api-1', displayName: 'OpenAI Whisper', isApiModel: true },
];

describe('TranscriptionModelPickerMenu', () => {
  it('disables the fullLabel trigger while recording', () => {
    const state = { ...initialTranscriptionState, availableTranscriptionModels: models, isRecording: true };
    render(<TranscriptionModelPickerMenu state={state} style="fullLabel" />);
    expect(screen.getByRole('button', { name: /transcription model/i })).toBeDisabled();
  });

  it('keeps the miniChevron trigger enabled while recording', () => {
    const state = { ...initialTranscriptionState, availableTranscriptionModels: models, isRecording: true };
    render(<TranscriptionModelPickerMenu state={state} style="miniChevron" />);
    expect(screen.getByRole('button', { name: /transcription model/i })).toBeEnabled();
  });

  it('disables both variants while a swap is in flight', () => {
    const state = { ...initialTranscriptionState, availableTranscriptionModels: models, isSwappingTranscriptionModel: true };
    render(<TranscriptionModelPickerMenu state={state} style="miniChevron" />);
    expect(screen.getByRole('button', { name: /transcription model/i })).toBeDisabled();
  });

  it('opens the full picker through the native menu bridge', async () => {
    const state = {
      ...initialTranscriptionState,
      availableTranscriptionModels: models,
      currentTranscriptionModelId: 'local-1',
    };
    render(<TranscriptionModelPickerMenu state={state} style="fullLabel" />);
    const trigger = screen.getByRole('button', { name: /transcription model/i });
    expect(trigger).toHaveAccessibleName('Transcription model');
    await userEvent.click(trigger);
    expect(bridge.showTranscriptionModelMenu).toHaveBeenCalledWith(
      models,
      'local-1',
      expect.objectContaining({ x: expect.any(Number), y: expect.any(Number), width: expect.any(Number), height: expect.any(Number) }),
    );
  });

  it('opens the compact picker through the native menu bridge', async () => {
    const state = { ...initialTranscriptionState, availableTranscriptionModels: models, currentTranscriptionModelId: 'local-1' };
    render(<TranscriptionModelPickerMenu state={state} style="miniChevron" />);

    await userEvent.click(screen.getByRole('button', { name: /transcription model/i }));

    expect(bridge.showTranscriptionModelMenu).toHaveBeenCalledWith(
      models,
      'local-1',
      expect.objectContaining({ x: expect.any(Number), y: expect.any(Number), width: expect.any(Number), height: expect.any(Number) }),
    );
  });
});
