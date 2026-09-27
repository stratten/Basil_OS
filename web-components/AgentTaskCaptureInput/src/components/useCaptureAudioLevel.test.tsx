// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import VoiceCaptureView from './VoiceCaptureView';
import { voiceRecordingSnapshot } from '../fixtures/captureFixtures';

const animatedBubbleMock = vi.hoisted(() => vi.fn((_props: { audioLevel: number }) => <canvas data-testid="animated-bubble" />));

vi.mock('../../../shared/bubble/AnimatedBubble', () => ({
  default: animatedBubbleMock,
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
let captureHeaderRenderCount = 0;

function CaptureHeader() {
  captureHeaderRenderCount += 1;
  return <div data-testid="capture-header" />;
}

beforeEach(() => {
  animatedBubbleMock.mockClear();
  captureHeaderRenderCount = 0;
  window.webkit = { messageHandlers: { agentTaskCaptureBridge: { postMessage: vi.fn() } } };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  container.remove();
});

describe('useCaptureAudioLevel', () => {
  it('isolates meter updates and unregisters on unmount', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const onModelChange = vi.fn();

    act(() => {
      root.render(
        <>
          <CaptureHeader />
          <VoiceCaptureView
            snapshot={voiceRecordingSnapshot}
            selectedModelId={null}
            onModelChange={onModelChange}
          />
        </>,
      );
    });
    expect(captureHeaderRenderCount).toBe(1);

    act(() => {
      window.basilAgentTaskCapture!.onAudioLevel(0.3, 1);
      window.basilAgentTaskCapture!.onAudioLevel(0.8, 2);
    });

    expect(captureHeaderRenderCount).toBe(1);
    expect(animatedBubbleMock.mock.calls[animatedBubbleMock.mock.calls.length - 1]?.[0]).toMatchObject({ audioLevel: 0.8 });

    act(() => {
      root.unmount();
    });
    act(() => {
      window.basilAgentTaskCapture!.onAudioLevel(0.5, 3);
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
