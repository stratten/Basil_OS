import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { TranscriptionWidgetApp } from './TranscriptionWidgetApp';
import type { TranscriptionBridgeEvent } from '../bridge/types';

let eventListener: ((event: TranscriptionBridgeEvent) => void) | null = null;
let fullWidgetRenderCount = 0;
let minimizedWidgetRenderCount = 0;

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  onTranscriptionEvent: (listener: (event: TranscriptionBridgeEvent) => void) => {
    eventListener = listener;
    return () => {
      eventListener = null;
    };
  },
  reportReady: vi.fn(),
}));

vi.mock('../components/FullWidget', () => ({
  FullWidget: () => {
    fullWidgetRenderCount += 1;
    return <div data-testid="full-widget-stub" />;
  },
}));

vi.mock('../components/MinimizedWidget', () => ({
  MinimizedWidget: () => {
    minimizedWidgetRenderCount += 1;
    return <div data-testid="minimized-widget-stub" />;
  },
}));

beforeEach(() => {
  eventListener = null;
  fullWidgetRenderCount = 0;
  minimizedWidgetRenderCount = 0;
});

describe('TranscriptionWidgetApp', () => {
  it('renders the full widget by default and switches to minimized on a snapshot', () => {
    render(<TranscriptionWidgetApp />);
    expect(document.querySelector('.basil-webkit-window-frame')).toBeInTheDocument();
    expect(document.querySelector('.basil-webkit-window-surface')).toBeInTheDocument();
    expect(screen.getByTestId('full-widget-stub')).toBeInTheDocument();

    act(() => {
    eventListener?.({
      type: 'snapshot',
      revision: 1,
      protocolVersion: 1,
      isRecording: false,
      isStartingRecording: false,
      isProcessingRecording: false,
      isConnected: true,
      isModelReady: true,
      isModelLoading: false,
      error: null,
      transcriptionText: 'Ready to record',
      audioLevel: 0,
      elapsedSeconds: 0,
      isMinimized: true,
      canToggleRecording: true,
      currentTranscriptionModelId: '',
      availableTranscriptionModels: [],
      isSwappingTranscriptionModel: false,
      hotkeyDisplayString: null,
      bubbleMode: 'ambient',
      bubbleColors: { base: '#000', accent: '#111' },
    });
    });

    expect(document.querySelector('.transcription-widget-window-frame--minimized')).toBeInTheDocument();
    expect(document.querySelector('.transcription-widget-window-frame--minimized .basil-webkit-window-surface')).toBeInTheDocument();
    expect(screen.getByTestId('minimized-widget-stub')).toBeInTheDocument();
  });

  it('does not re-render FullWidget or MinimizedWidget when the meter store updates', async () => {
    const { publishTranscriptionMeter } = await import('../bridge/transcriptionMeterStore');
    render(<TranscriptionWidgetApp />);
    const rendersBeforeMeter = fullWidgetRenderCount;

    act(() => {
      publishTranscriptionMeter(0.5);
      publishTranscriptionMeter(0.8);
    });

    expect(fullWidgetRenderCount).toBe(rendersBeforeMeter);
    expect(minimizedWidgetRenderCount).toBe(0);
  });
});
