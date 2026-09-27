import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { publishTranscriptionMeter, useTranscriptionMeter } from './transcriptionMeterStore';
import { onTranscriptionEvent } from './transcriptionWidgetBridge';

describe('transcriptionWidgetBridge', () => {
  it('delivers queued events once a listener is registered', () => {
    window.basilTranscriptionWidget?.onEvent({
      type: 'themeChanged',
      primary: '#111',
      secondary: '#222',
      backgroundPrimary: '#fff',
      textPrimary: '#000',
      textSecondary: '#333',
      recordingBase: '#f00',
      errorBase: '#f00',
      warningBase: '#ff0',
      preferredFontName: 'System',
    });
    const listener = vi.fn();
    const unsubscribe = onTranscriptionEvent(listener);

    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ type: 'themeChanged' }));

    unsubscribe();
  });

  it('publishes incoming meter events to the transcription meter store', () => {
    publishTranscriptionMeter(0);
    const { result } = renderHook(() => useTranscriptionMeter());

    act(() => {
      window.basilTranscriptionWidget?.onEvent({ type: 'meter', audioLevel: 0.65 });
    });

    expect(result.current).toBe(0.65);
  });
});
