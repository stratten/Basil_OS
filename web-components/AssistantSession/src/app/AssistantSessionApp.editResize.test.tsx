import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { AssistantSessionApp } from './AssistantSessionApp';

const {
  revision: _revision,
  hasSnapshot: _hasSnapshot,
  theme: _theme,
  ...basePayload
} = initialAssistantSessionState;

describe('AssistantSessionApp edit-mode sizing', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList.contains('assistant-session-result__edit-textarea')
          || this.classList.contains('assistant-session-result__output')
          ? 850
          : 0;
      },
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
  });

  it('keeps the window sized to content when a result switches to edit mode', () => {
    render(<AssistantSessionApp />);

    act(() => {
      window.basilAssistantSession?.onEvent({
        type: 'snapshot',
        protocolVersion: 1,
        revision: 1,
        ...basePayload,
        assistantSessionStatus: 'completed',
        assistantOutput: 'Long output',
        editableContentSeed: 'Long output',
        shouldPersistUI: true,
      });
    });
    act(() => {
      window.basilAssistantSession?.onEvent({
        type: 'snapshot',
        protocolVersion: 1,
        revision: 2,
        ...basePayload,
        assistantSessionStatus: 'completed',
        assistantOutput: 'Long output',
        editableContentSeed: 'Long output',
        isEditMode: true,
        shouldPersistUI: true,
      });
    });

    const resizeCalls = postMessage.mock.calls
      .map(([message]) => message as { type: string; height?: number })
      .filter((message) => message.type === 'requestResize');
    expect(resizeCalls[resizeCalls.length - 1]?.height).toBe(850);
  });

  it('grows the window when the paste status chip appears after the output', () => {
    const originalInnerHeight = window.innerHeight;
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 300 });
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList.contains('assistant-session-result__output') ? 400 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get(this: HTMLElement) {
        if (this.classList.contains('basil-webkit-window-frame')) return 450;
        if (this.classList.contains('assistant-session-result__output')) {
          return document.querySelector('.assistant-session-result__paste-status') ? 250 : 280;
        }
        return 0;
      },
    });
    const completedPayload = {
      protocolVersion: 1,
      ...basePayload,
      assistantSessionStatus: 'completed' as const,
      assistantOutput: 'Hey Sam,\n\nThursday works.',
      shouldPersistUI: true,
    };

    try {
      render(<AssistantSessionApp />);
      act(() => {
        window.basilAssistantSession?.onEvent({ type: 'snapshot', revision: 1, ...completedPayload });
      });
      const lastResizeHeight = () => {
        const resizeCalls = postMessage.mock.calls
          .map(([message]) => message as { type: string; height?: number })
          .filter((message) => message.type === 'requestResize');
        return resizeCalls[resizeCalls.length - 1]?.height;
      };
      expect(lastResizeHeight()).toBe(570);

      act(() => {
        window.basilAssistantSession?.onEvent({
          type: 'snapshot',
          revision: 2,
          ...completedPayload,
          pasteOutcome: 'pasted',
          pasteTargetApplicationName: 'TextEdit',
        });
      });
      expect(lastResizeHeight()).toBe(600);
    } finally {
      Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight');
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalInnerHeight });
    }
  });
});
