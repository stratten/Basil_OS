// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSwiftBridge, hasSwiftHandler, missingHandlerLogger, postToSwiftHandler } from './swiftBridge';

afterEach(() => {
  window.webkit = undefined;
  vi.restoreAllMocks();
});

function installHandler(name: string) {
  const postMessage = vi.fn();
  window.webkit = { messageHandlers: { [name]: { postMessage } } };
  return postMessage;
}

describe('postToSwiftHandler', () => {
  it('delivers the same message object to the named handler and reports success', () => {
    const postMessage = installHandler('sampleBridge');
    const message = { type: 'ping' };

    expect(postToSwiftHandler('sampleBridge', message)).toBe(true);

    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage.mock.calls[0][0]).toBe(message);
  });

  it('does not deliver to a different handler', () => {
    const other = vi.fn();
    const target = vi.fn();
    window.webkit = { messageHandlers: { otherBridge: { postMessage: other }, targetBridge: { postMessage: target } } };

    postToSwiftHandler('targetBridge', { type: 'ping' });

    expect(target).toHaveBeenCalledTimes(1);
    expect(other).not.toHaveBeenCalled();
  });

  it('returns false and reports the dropped message when window.webkit is absent', () => {
    window.webkit = undefined;
    const onMissing = vi.fn();
    const message = { type: 'ping' };

    expect(postToSwiftHandler('sampleBridge', message, onMissing)).toBe(false);

    expect(onMissing).toHaveBeenCalledTimes(1);
    expect(onMissing).toHaveBeenCalledWith(message);
  });

  it('returns false when window.webkit has no handlers or the named handler is missing', () => {
    const onMissing = vi.fn();

    window.webkit = { messageHandlers: {} };
    expect(postToSwiftHandler('sampleBridge', 1, onMissing)).toBe(false);

    window.webkit = {} as unknown as Window['webkit'];
    expect(postToSwiftHandler('sampleBridge', 2, onMissing)).toBe(false);

    expect(onMissing).toHaveBeenNthCalledWith(1, 1);
    expect(onMissing).toHaveBeenNthCalledWith(2, 2);
  });

  it('does not call onMissing when the message is delivered', () => {
    installHandler('sampleBridge');
    const onMissing = vi.fn();

    postToSwiftHandler('sampleBridge', { type: 'ping' }, onMissing);

    expect(onMissing).not.toHaveBeenCalled();
  });

  it('propagates an exception thrown by the native handler without reporting it as missing', () => {
    const postMessage = installHandler('sampleBridge');
    postMessage.mockImplementation(() => {
      throw new Error('boom');
    });
    const onMissing = vi.fn();

    expect(() => postToSwiftHandler('sampleBridge', { type: 'ping' }, onMissing)).toThrow('boom');
    expect(onMissing).not.toHaveBeenCalled();
  });

  it('passes special characters and very long payloads through unchanged', () => {
    const postMessage = installHandler('sampleBridge');
    const payload = { text: `quote " backslash \\ newline \n unicode \u{1F33F} ${'x'.repeat(100_000)}` };

    postToSwiftHandler('sampleBridge', payload);

    expect(postMessage.mock.calls[0][0]).toBe(payload);
    expect((postMessage.mock.calls[0][0] as typeof payload).text.length).toBe(payload.text.length);
  });
});

describe('hasSwiftHandler', () => {
  it('tracks installation and removal of the handler', () => {
    expect(hasSwiftHandler('sampleBridge')).toBe(false);

    installHandler('sampleBridge');
    expect(hasSwiftHandler('sampleBridge')).toBe(true);
    expect(hasSwiftHandler('otherBridge')).toBe(false);

    window.webkit = undefined;
    expect(hasSwiftHandler('sampleBridge')).toBe(false);
  });
});

describe('createSwiftBridge', () => {
  it('resolves the handler at call time, not at creation time', () => {
    const onMissing = vi.fn();
    const bridge = createSwiftBridge<{ type: string }>('sampleBridge', { onMissing });

    expect(bridge.handlerName).toBe('sampleBridge');
    expect(bridge.isAvailable()).toBe(false);
    expect(bridge.post({ type: 'early' })).toBe(false);
    expect(onMissing).toHaveBeenCalledWith({ type: 'early' });

    const postMessage = installHandler('sampleBridge');
    expect(bridge.isAvailable()).toBe(true);
    expect(bridge.post({ type: 'late' })).toBe(true);
    expect(postMessage).toHaveBeenCalledWith({ type: 'late' });
  });

  it('is silent when no reporter is configured', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const bridge = createSwiftBridge('sampleBridge');

    expect(bridge.post({ type: 'ping' })).toBe(false);

    expect(log).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
  });
});

describe('missingHandlerLogger', () => {
  it('logs the exact text and message at the requested level only', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const message = { type: 'ping' };

    missingHandlerLogger('log', '[Sample] No Swift handler, message:')(message);
    expect(log).toHaveBeenCalledWith('[Sample] No Swift handler, message:', message);
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();

    missingHandlerLogger('warn', '[Sample] dropped')(message);
    expect(warn).toHaveBeenCalledWith('[Sample] dropped', message);

    missingHandlerLogger('error', '[Sample] unavailable')(message);
    expect(error).toHaveBeenCalledWith('[Sample] unavailable', message);
  });
});
