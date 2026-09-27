// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  notifyLocalPreviewServerSessionDenied,
  notifyLocalPreviewServerSessionStarted,
  notifyLocalWebPreviewWindowWillClose,
  readCurrentPreviewUrl,
  registerLocalWebPreviewValidationFeedbackHandler,
  registerLocalWebPreviewValidationServerHandler,
} from './localWebPreviewBridge';

function armPostMessage() {
  const postMessage = vi.fn();
  window.webkit = { messageHandlers: { localWebPreviewBridge: { postMessage } } } as unknown as Window['webkit'];
  return postMessage;
}

describe('readCurrentPreviewUrl', () => {
  it('returns the live iframe location as current when it is readable and non-empty', () => {
    const frame = {
      contentWindow: { location: { href: 'http://127.0.0.1:4173/dashboard' } },
    } as unknown as HTMLIFrameElement;

    expect(readCurrentPreviewUrl(frame, 'http://127.0.0.1:4173/')).toEqual({
      url: 'http://127.0.0.1:4173/dashboard',
      status: 'current',
    });
  });

  it('falls back to the supplied URL when reading the location throws', () => {
    const frame = {
      get contentWindow() {
        throw new DOMException('Blocked a frame with origin from accessing a cross-origin frame.', 'SecurityError');
      },
    } as unknown as HTMLIFrameElement;

    expect(readCurrentPreviewUrl(frame, 'http://127.0.0.1:4173/')).toEqual({
      url: 'http://127.0.0.1:4173/',
      status: 'fallback',
    });
  });

  it('falls back to the supplied URL when there is no frame', () => {
    expect(readCurrentPreviewUrl(null, 'http://127.0.0.1:4173/')).toEqual({
      url: 'http://127.0.0.1:4173/',
      status: 'fallback',
    });
  });
});

describe('notifyLocalWebPreviewWindowWillClose', () => {
  afterEach(() => {
    delete (window as { webkit?: unknown }).webkit;
  });

  it('posts a previewWindowWillClose message to the native host', () => {
    const postMessage = armPostMessage();
    notifyLocalWebPreviewWindowWillClose();
    expect(postMessage).toHaveBeenCalledWith({ type: 'previewWindowWillClose' });
  });

  it('posts the started preview-server session ID to the native host', () => {
    const postMessage = armPostMessage();
    notifyLocalPreviewServerSessionStarted('session-42');
    expect(postMessage).toHaveBeenCalledWith({
      type: 'previewServerSessionStarted',
      sessionId: 'session-42',
    });
  });

  it('posts the denied preview-server session ID and reason to the native host', () => {
    const postMessage = armPostMessage();
    notifyLocalPreviewServerSessionDenied('session-99', 'Denied by validation policy');
    expect(postMessage).toHaveBeenCalledWith({
      type: 'previewServerSessionDenied',
      sessionId: 'session-99',
      lastError: 'Denied by validation policy',
    });
  });
});

describe('validation callbacks', () => {
  it('delivers validation feedback only while the handler is registered', () => {
    const callback = vi.fn();
    const unregister = registerLocalWebPreviewValidationFeedbackHandler(callback);

    window.basilLocalWebPreview?.onValidationFeedback({ text: 'Capture the current rendered state.' });
    unregister();
    window.basilLocalWebPreview?.onValidationFeedback({ text: 'This must not submit again.' });

    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith({ text: 'Capture the current rendered state.' });
  });

  it('delivers a structured validation server request only while registered', () => {
    const callback = vi.fn();
    const unregister = registerLocalWebPreviewValidationServerHandler(callback);
    const payload = {
      command: 'python3',
      args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
      cwd: '/tmp/local-preview',
      port: 43123,
    };

    window.basilLocalWebPreview?.onValidationStartServer(payload);
    unregister();
    window.basilLocalWebPreview?.onValidationStartServer(payload);

    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith(payload);
  });
});
