import { describe, expect, it } from 'vitest';
import { applyTranscriptionEvent, initialTranscriptionState } from './transcriptionReducer';
import { PROTOCOL_VERSION } from '../bridge/types';

const {
  revision: _revision,
  hasSnapshot: _hasSnapshot,
  theme: _theme,
  ...basePayload
} = initialTranscriptionState;

describe('transcriptionReducer', () => {
  it('applies a snapshot unconditionally and seeds revision', () => {
    const next = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'snapshot',
      revision: 5,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
      transcriptionText: 'hello',
    });
    expect(next.revision).toBe(5);
    expect(next.transcriptionText).toBe('hello');
    expect(next.hasSnapshot).toBe(true);
  });

  it('applies a delta whose revision is strictly greater than the current revision', () => {
    const seeded = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'snapshot',
      revision: 1,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
    });
    const next = applyTranscriptionEvent(seeded, {
      type: 'delta',
      revision: 2,
      protocolVersion: PROTOCOL_VERSION,
      transcriptionText: 'partial',
    });
    expect(next.revision).toBe(2);
    expect(next.transcriptionText).toBe('partial');
  });

  it('drops a delta whose revision is not strictly greater than the applied revision', () => {
    const seeded = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'snapshot',
      revision: 4,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
      transcriptionText: 'keep-me',
    });
    const next = applyTranscriptionEvent(seeded, {
      type: 'delta',
      revision: 4,
      protocolVersion: PROTOCOL_VERSION,
      transcriptionText: 'stale',
    });
    expect(next.revision).toBe(4);
    expect(next.transcriptionText).toBe('keep-me');
  });

  it('rejects a snapshot from an unsupported protocol version and leaves state untouched', () => {
    const next = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'snapshot',
      revision: 1,
      protocolVersion: PROTOCOL_VERSION + 1,
      ...basePayload,
      transcriptionText: 'should-not-apply',
    });
    expect(next).toBe(initialTranscriptionState);
  });

  it('ignores meter events entirely', () => {
    const next = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'meter',
      audioLevel: 0.42,
    });
    expect(next).toBe(initialTranscriptionState);
  });

  it('stores theme from init and themeChanged', () => {
    const themed = applyTranscriptionEvent(initialTranscriptionState, {
      type: 'init',
      protocolVersion: PROTOCOL_VERSION,
      theme: {
        primary: '#111111',
        secondary: '#222222',
        backgroundPrimary: '#ffffff',
        textPrimary: '#000000',
        textSecondary: '#333333',
        recordingBase: '#440000',
        errorBase: '#550000',
        warningBase: '#666600',
        preferredFontName: 'Helvetica',
      },
    });
    expect(themed.theme?.primary).toBe('#111111');

    const changed = applyTranscriptionEvent(themed, {
      type: 'themeChanged',
      primary: '#aaaaaa',
      secondary: '#222222',
      backgroundPrimary: '#ffffff',
      textPrimary: '#000000',
      textSecondary: '#333333',
      recordingBase: '#440000',
      errorBase: '#550000',
      warningBase: '#666600',
      preferredFontName: 'Helvetica',
    });
    expect(changed.theme?.primary).toBe('#aaaaaa');
  });
});
