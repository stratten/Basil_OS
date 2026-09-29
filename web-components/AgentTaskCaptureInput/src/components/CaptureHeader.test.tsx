// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import CaptureHeader from './CaptureHeader';
import type { CaptureInputMessage } from '../types';
import { baseTextSnapshot, baseVoiceSnapshot } from '../fixtures/captureFixtures';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
let postMessage: Mock<(message: CaptureInputMessage) => void>;

beforeEach(() => {
  postMessage = vi.fn<(message: CaptureInputMessage) => void>();
  window.webkit = { messageHandlers: { agentTaskCaptureBridge: { postMessage } } };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(snapshot: ReturnType<typeof baseVoiceSnapshot>) {
  act(() => {
    root.render(<CaptureHeader snapshot={snapshot} displayName="Paprika" />);
  });
}

function click(label: string) {
  const button = container.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement;
  expect(button).not.toBeNull();
  act(() => button.click());
}

describe('CaptureHeader', () => {
  it('dispatches cancellation from its leading control', () => {
    render(baseVoiceSnapshot());

    click('Cancel agent task');

    expect(postMessage).toHaveBeenCalledWith({ type: 'cancelCapture' });
  });

  it('reports the measured header extent to the native drag surface', () => {
    const geometrySpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('basil-webkit-window-frame')) return new DOMRect(0, 0, 160, 180);
      return new DOMRect(4, 4, 152, 24);
    });

    try {
      act(() => {
        root.render(
          <div className="basil-webkit-window-frame">
            <CaptureHeader snapshot={baseVoiceSnapshot()} displayName="Paprika" />
          </div>,
        );
      });

      expect(postMessage).toHaveBeenCalledWith({ type: 'captureHeaderExtent', height: 28 });
    } finally {
      geometrySpy.mockRestore();
    }
  });

  it('dispatches the history action from its trailing control', () => {
    render(baseVoiceSnapshot());

    click('Show agent task history');

    expect(postMessage).toHaveBeenCalledWith({ type: 'showHistory' });
  });

  it('switches from voice to text entry', () => {
    render(baseVoiceSnapshot());

    click('Switch to text entry');

    expect(postMessage).toHaveBeenCalledWith({ type: 'enterTextEntryMode' });
  });

  it('switches from text entry to voice capture', () => {
    render(baseTextSnapshot());

    click('Switch to voice capture');

    expect(postMessage).toHaveBeenCalledWith({ type: 'enterVoiceMode' });
  });
});
