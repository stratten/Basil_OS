import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { AssistantSessionApp } from './AssistantSessionApp';

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
        ...initialAssistantSessionState,
        hasSnapshot: true,
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
        ...initialAssistantSessionState,
        hasSnapshot: true,
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
});
