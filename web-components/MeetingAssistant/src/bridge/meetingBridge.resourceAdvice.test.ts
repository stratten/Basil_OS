// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { openAppSettings } from './meetingBridge';

afterEach(() => {
  window.webkit = undefined;
  vi.restoreAllMocks();
});

describe('resource advice bridge addition', () => {
  it('posts the openAppSettings intent with no payload', () => {
    const postMessage = vi.fn();
    window.webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    openAppSettings();
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([{ type: 'openAppSettings' }]);
  });
});
