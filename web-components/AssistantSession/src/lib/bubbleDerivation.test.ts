// web-components/AssistantSession/src/lib/bubbleDerivation.test.ts

import { describe, expect, it } from 'vitest';
import { deriveBubbleColors, deriveBubbleMode, isAssistantSessionProcessing } from './bubbleDerivation';

const theme = {
  primary: '#000',
  secondary: '#111',
  backgroundPrimary: '#fff',
  backgroundSecondary: '#eee',
  textPrimary: '#000',
  textSecondary: '#333',
  textTertiary: '#666',
  recordingBase: '#8B0000',
  recordingAccent: '#C23B3B',
  readyBase: '#2F6FED',
  readyAccent: '#8FB2F7',
  processingBase: '#7C3AED',
  processingAccent: '#DDD6FE',
  successBase: '#1E8E5A',
  errorBase: '#D33B3B',
  preferredFontName: 'Inter',
};

describe('bubbleDerivation', () => {
  it('is processing when any of ocr/transcription/assistantSession is running', () => {
    expect(isAssistantSessionProcessing('running', 'idle', 'idle')).toBe(true);
    expect(isAssistantSessionProcessing('idle', 'running', 'idle')).toBe(true);
    expect(isAssistantSessionProcessing('idle', 'idle', 'running')).toBe(true);
    expect(isAssistantSessionProcessing('idle', 'idle', 'idle')).toBe(false);
  });

  it('prioritizes recording mode over processing', () => {
    expect(deriveBubbleMode(true, 'running', 'running', 'running')).toBe('audioResponsive');
  });

  it('falls back to processing then ambient', () => {
    expect(deriveBubbleMode(false, 'running', 'idle', 'idle')).toBe('processing');
    expect(deriveBubbleMode(false, 'idle', 'idle', 'idle')).toBe('ambient');
  });

  it('derives recording colors while recording regardless of processing state', () => {
    expect(deriveBubbleColors(true, true, theme)).toEqual({ base: theme.recordingBase, accent: theme.recordingAccent });
  });

  it('derives processing colors when not recording but processing', () => {
    expect(deriveBubbleColors(false, true, theme)).toEqual({ base: theme.processingBase, accent: theme.processingAccent });
  });

  it('derives ready/idle colors when neither recording nor processing', () => {
    expect(deriveBubbleColors(false, false, theme)).toEqual({ base: theme.readyBase, accent: theme.readyAccent });
  });
});
