// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { focusCompanionItem, focusTranscript, openCompanionWindow, pickCompanionFolder, setCompanionPaneExtent, subscribeFilesDropped } from './meetingBridge';

afterEach(() => {
  window.webkit = undefined;
  vi.restoreAllMocks();
});

describe('Companion bridge additions', () => {
  it('posts the new intents to the meetingBridge handler', () => {
    const postMessage = vi.fn();
    window.webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    pickCompanionFolder();
    openCompanionWindow();
    setCompanionPaneExtent(340);
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([{ type: 'pickCompanionFolder' }, { type: 'openCompanionWindow' }, { type: 'setCompanionPaneExtent', width: 340 }]);
  });

  it('posts the link-following intents', () => {
    const postMessage = vi.fn();
    window.webkit = { messageHandlers: { meetingBridge: { postMessage } } };
    focusTranscript('item-1', 3, 9.5);
    focusCompanionItem('item-1');
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([
      { type: 'focusTranscript', itemId: 'item-1', startSeconds: 3, endSeconds: 9.5 },
      { type: 'focusCompanionItem', itemId: 'item-1' },
    ]);
  });

  it('delivers dropped paths to subscribers and stops after unsubscribe', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeFilesDropped(listener);
    window.basilMeetingAssistant?.onFilesDropped?.({ paths: ['/a', '/b'], source: 'drop' });
    expect(listener).toHaveBeenCalledWith({ paths: ['/a', '/b'], source: 'drop' });
    unsubscribe();
    window.basilMeetingAssistant?.onFilesDropped?.({ paths: ['/c'], source: 'drop' });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('drops malformed payloads and normalizes an unknown source to drop', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeFilesDropped(listener);
    const deliver = window.basilMeetingAssistant?.onFilesDropped as ((payload: unknown) => void) | undefined;
    deliver?.(null);
    deliver?.({ paths: 'nope', source: 'drop' });
    deliver?.({ paths: ['', 7], source: 'drop' });
    expect(listener).not.toHaveBeenCalled();
    deliver?.({ paths: ['/ok', 3], source: 'weird' });
    expect(listener).toHaveBeenCalledWith({ paths: ['/ok'], source: 'drop' });
    unsubscribe();
  });
});
