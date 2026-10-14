import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EMPTY_COMPANION_STATUS, type CompanionSnapshot, type CompanionSocketEvent } from './types';

const { sockets, FakeSocket } = vi.hoisted(() => {
  const created: Array<{
    handlers: Array<(frame: CompanionSocketEvent) => void>;
    url: string;
    disconnected: boolean;
    emit: (frame: CompanionSocketEvent) => void;
  }> = [];

  class HoistedFakeSocket {
    handlers: Array<(frame: CompanionSocketEvent) => void> = [];
    connectHandlers: Array<() => void> = [];
    url = '';
    disconnected = false;
    constructor() {
      created.push(this);
    }
    subscribe(handler: (frame: CompanionSocketEvent) => void) {
      this.handlers.push(handler);
      return () => undefined;
    }
    onConnect(handler: () => void) {
      this.connectHandlers.push(handler);
      return () => undefined;
    }
    connect(url: string) {
      this.url = url;
    }
    disconnect() {
      this.disconnected = true;
    }
    emit(frame: CompanionSocketEvent) {
      for (const handler of this.handlers) handler(frame);
    }
  }

  return { sockets: created, FakeSocket: HoistedFakeSocket };
});

vi.mock('@shared/websocket/reconnectingWebSocket', () => ({ ReconnectingWebSocket: FakeSocket }));

import { useCompanion } from './useCompanion';

function snapshot(overrides: Partial<CompanionSnapshot> = {}): CompanionSnapshot {
  return {
    meeting_id: 'm1',
    session_key: 's1',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    roots: [],
    items: [],
    watches: [],
    chat: [],
    retrievals: [],
    last_seq: 0,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('useCompanion', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    sockets.length = 0;
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('stays idle without a meeting or a port and makes no request', () => {
    const { result } = renderHook(() => useCompanion({ meetingId: null, port: 0, selectedModelId: null }));
    expect(result.current.state.phase).toBe('idle');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sockets).toHaveLength(0);
  });

  it('hydrates from the snapshot and connects the socket to the loopback port', async () => {
    fetchMock.mockResolvedValue(jsonResponse(snapshot()));
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8123/meetings/m1/companion');
    expect(sockets[0].url).toBe('ws://127.0.0.1:8123/ws');
    expect(result.current.isEnabled).toBe(true);
  });

  it('applies a persisted event for the displayed meeting and ignores other meetings', async () => {
    fetchMock.mockResolvedValue(jsonResponse(snapshot()));
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    const itemPayload = {
      id: 'i1', kind: 'insight', text: 'hello', confidence: 0.5, citations: [], no_source: false,
      transcript_range: { start: 0, end: 1, turn_ids: [] }, trigger: 'periodic', watch_id: null, truncated: false, pinned: false, dismissed: false,
    };
    act(() => {
      sockets[0].emit({
        event_type: 'meeting_companion_event',
        session_key: 'other',
        meeting_ids: ['m9'],
        event: { id: 'e1', seq: 1, kind: 'item', meeting_time: 1, wall_time: '', payload: { item: itemPayload } },
      });
    });
    expect(result.current.state.timeline.items).toHaveLength(0);
    act(() => {
      sockets[0].emit({
        event_type: 'meeting_companion_event',
        session_key: 's1',
        meeting_ids: ['m1', 'm2'],
        event: { id: 'e1', seq: 1, kind: 'item', meeting_time: 1, wall_time: '', payload: { item: itemPayload } },
      });
    });
    expect(result.current.state.timeline.items.map((entry) => entry.id)).toEqual(['i1']);
  });

  it('keeps added sources pending while the Companion is off and attaches them after enable', async () => {
    const offSnapshot = snapshot({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false } });
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/enable')) return Promise.resolve(jsonResponse(snapshot()));
      if (url.endsWith('/roots') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ id: 'r1', path: '/tmp/p', display_name: 'p', kind: 'folder', attached_at: 0, detached_at: null }, 201));
      }
      return Promise.resolve(jsonResponse(offSnapshot));
    });
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: 'model-a', isRecording: true }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    await act(async () => {
      await result.current.addRoots(['/tmp/p', '/tmp/p', '  ']);
    });
    expect(result.current.pendingRoots).toEqual(['/tmp/p']);
    await act(async () => {
      await result.current.enable();
    });
    const enableCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/enable'));
    expect(JSON.parse(String(enableCall?.[1]?.body))).toEqual({ model_id: 'model-a' });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/roots') && init?.method === 'POST')).toBe(true));
    await waitFor(() => expect(result.current.pendingRoots).toEqual([]));
  });

  it('attaches sources queued before recording when the Companion turns on by itself at the start of the recording', async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/roots') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ id: 'r1', path: '/tmp/p', display_name: 'p', kind: 'folder', attached_at: 0, detached_at: null }, 201));
      }
      return Promise.resolve(jsonResponse(snapshot({ meeting_id: 'live-1' })));
    });
    const { result, rerender } = renderHook((props: { meetingId: string | null; isRecording: boolean }) => useCompanion({ meetingId: props.meetingId, port: 8123, selectedModelId: null, isRecording: props.isRecording }), {
      initialProps: { meetingId: null as string | null, isRecording: false },
    });
    await act(async () => {
      await result.current.addRoots(['/tmp/p']);
    });
    expect(result.current.pendingRoots).toEqual(['/tmp/p']);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/roots'))).toBe(false);
    rerender({ meetingId: 'live-1', isRecording: true });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/live-1/companion/roots') && init?.method === 'POST')).toBe(true));
    await waitFor(() => expect(result.current.pendingRoots).toEqual([]));
  });

  it('keeps sources queued while the recording meeting has not turned its Companion on', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(snapshot({ status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: false } }))));
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null, isRecording: true }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    await act(async () => {
      await result.current.addRoots(['/tmp/p']);
    });
    expect(result.current.pendingRoots).toEqual(['/tmp/p']);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/roots'))).toBe(false);
  });

  it('surfaces the backend detail string when an action is rejected', async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/chat') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ detail: 'The Companion is only available while this meeting is recording with the Companion turned on.' }, 409));
      }
      return Promise.resolve(jsonResponse(snapshot()));
    });
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    await act(async () => {
      await result.current.sendChat('hello');
    });
    expect(result.current.actionError).toContain('only available while this meeting is recording');
    act(() => result.current.clearActionError());
    expect(result.current.actionError).toBeNull();
  });

  it('patches the model when the picker selection differs from the live status', async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/settings') && init?.method === 'PATCH') return Promise.resolve(jsonResponse({ ...EMPTY_COMPANION_STATUS, live: true, enabled: true, model_id: 'model-b' }));
      return Promise.resolve(jsonResponse(snapshot()));
    });
    renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: 'model-b' }));
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ model_id: 'model-b' });
    });
  });

  it('refetches the snapshot after a sequence gap', async () => {
    fetchMock.mockResolvedValue(jsonResponse(snapshot()));
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    const callsBefore = fetchMock.mock.calls.length;
    act(() => {
      sockets[0].emit({
        event_type: 'meeting_companion_event',
        meeting_ids: ['m1'],
        event: { id: 'e5', seq: 5, kind: 'status', meeting_time: 1, wall_time: '', payload: {} },
      });
    });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it('disconnects the socket when the meeting changes or the hook unmounts', async () => {
    fetchMock.mockResolvedValue(jsonResponse(snapshot()));
    const { result, rerender, unmount } = renderHook(
      ({ meetingId }: { meetingId: string }) => useCompanion({ meetingId, port: 8123, selectedModelId: null }),
      { initialProps: { meetingId: 'm1' } },
    );
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    rerender({ meetingId: 'm2' });
    expect(sockets[0].disconnected).toBe(true);
    expect(sockets).toHaveLength(2);
    unmount();
    expect(sockets[1].disconnected).toBe(true);
  });
});
