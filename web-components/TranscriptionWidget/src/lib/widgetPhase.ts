// web-components/TranscriptionWidget/src/lib/widgetPhase.ts
//
// Mirrors TranscriptionWidget.swift's displayText/isStatusMessage computed
// properties (lines 40-56): derives display text and "is this a status
// message vs real transcript" purely from the booleans already in the
// snapshot, with no separate lifecycle enum on the wire.

import type { TranscriptionState } from '../state/transcriptionReducer';

export function resolveDisplayText(state: TranscriptionState): string {
  if (state.isRecording && (state.transcriptionText === 'Ready to record' || state.transcriptionText === '')) {
    return 'Recording in progress...';
  }
  if (state.isProcessingRecording && !state.isRecording && state.transcriptionText === 'Ready to record') {
    return 'Processing transcription...';
  }
  return state.transcriptionText;
}

export function isStatusMessage(displayText: string): boolean {
  return (
    displayText.startsWith('Starting') ||
    displayText.startsWith('Recording') ||
    displayText.startsWith('Processing') ||
    displayText.startsWith('Ready')
  );
}
