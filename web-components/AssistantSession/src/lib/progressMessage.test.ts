import { describe, expect, it } from 'vitest';
import { assistantSessionProgressMessage } from './progressMessage';

describe('assistantSessionProgressMessage', () => {
  it('returns Running OCR... while OCR is running', () => {
    expect(assistantSessionProgressMessage('running', 'idle', 'idle', null)).toBe('Running OCR...');
  });

  it('prefers the live transcription progress message while recording', () => {
    expect(assistantSessionProgressMessage('completed', 'running', 'idle', 'Transcribing chunk 2')).toBe(
      'Transcribing chunk 2',
    );
  });

  it('returns Uploading audio... after transcription completes and before generation starts', () => {
    expect(assistantSessionProgressMessage('completed', 'completed', 'idle', null)).toBe('Uploading audio...');
  });

  it('returns An error occurred. for a failed generation', () => {
    expect(assistantSessionProgressMessage('completed', 'completed', 'failed', null)).toBe('An error occurred.');
  });
});
