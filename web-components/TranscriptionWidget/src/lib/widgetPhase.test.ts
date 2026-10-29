import { describe, expect, it } from 'vitest';
import { resolveDisplayText, isStatusMessage } from './widgetPhase';
import { initialTranscriptionState } from '../state/transcriptionReducer';

function stateWith(overrides: Partial<typeof initialTranscriptionState>) {
  return { ...initialTranscriptionState, ...overrides };
}

describe('resolveDisplayText', () => {
  it('shows the recording placeholder when recording and text is still the ready message', () => {
    const state = stateWith({ isRecording: true, transcriptionText: 'Ready to record' });
    expect(resolveDisplayText(state)).toBe('Recording in progress...');
  });

  it('shows the recording placeholder when recording and text is empty', () => {
    const state = stateWith({ isRecording: true, transcriptionText: '' });
    expect(resolveDisplayText(state)).toBe('Recording in progress...');
  });

  it('shows the processing placeholder when processing, not recording, and text is still the ready message', () => {
    const state = stateWith({ isProcessingRecording: true, isRecording: false, transcriptionText: 'Ready to record' });
    expect(resolveDisplayText(state)).toBe('Processing transcription...');
  });

  it('passes through the real transcript once populated', () => {
    const state = stateWith({ isRecording: true, transcriptionText: 'hello world' });
    expect(resolveDisplayText(state)).toBe('hello world');
  });
});

describe('isStatusMessage', () => {
  it.each([
    ['Starting microphone...', true],
    ['Recording in progress...', true],
    ['Processing transcription...', true],
    ['Ready to record', true],
    ['hello world', false],
    ['', false],
  ])('classifies %j as status=%s', (text, expected) => {
    expect(isStatusMessage(text)).toBe(expected);
  });
});
