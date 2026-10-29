import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cloudState, jsonResponse } from './cloudTestFixtures';
import type { CloudTranscriptionState } from './cloudTranscriptionTypes';

type Frame = { event_type: string } & Record<string, unknown>;

const { sockets, FakeSocket } = vi.hoisted(() => {
  const created: Array<{
    handlers: Array<(frame: { event_type: string } & Record<string, unknown>) => void>;
    connectHandlers: Array<() => void>;
    url: string;
    disconnected: boolean;
  }> = [];

  class HoistedFakeSocket {
    handlers: Array<(frame: { event_type: string } & Record<string, unknown>) => void> = [];
    connectHandlers: Array<() => void> = [];
    url = '';
    disconnected = false;
    constructor() {
      created.push(this);
    }
    subscribe(handler: (frame: { event_type: string } & Record<string, unknown>) => void) {
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
  }
  return { sockets: created, FakeSocket: HoistedFakeSocket };
});

vi.mock('@shared/websocket/reconnectingWebSocket', () => ({ ReconnectingWebSocket: FakeSocket }));

import { useCloudTranscription } from './useCloudTranscription';

let serverState: CloudTranscriptionState;
let fetchMock: ReturnType<typeof vi.fn>;

function emit(frame: Frame) {
  for (const handler of sockets[sockets.length - 1].handlers) handler(frame);
}

beforeEach(() => {
  sockets.length = 0;
  serverState = cloudState();
  fetchMock = vi.fn(() => jsonResponse(serverState));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useCloudTranscription', () => {
  it('stays empty and opens nothing without a port', () => {
    const { result } = renderHook(() => useCloudTranscription(0));
    expect(result.current.state).toBeNull();
    expect(sockets).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('hydrates, subscribes to the backend socket and closes it on unmount', async () => {
    const { result, unmount } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).toEqual(serverState));
    expect(sockets).toHaveLength(1);
    expect(sockets[0].url).toBe('ws://127.0.0.1:8123/ws');
    unmount();
    expect(sockets[0].disconnected).toBe(true);
  });

  it('applies status frames, ignores other frames and malformed ones', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    act(() => emit({ event_type: 'cloud_transcription_status', state: 'streaming', provider: 'deepgram', tier: 'streaming', reason: null }));
    expect(result.current.state?.status.state).toBe('streaming');
    act(() => emit({ event_type: 'resource_advice', state: 'off' }));
    act(() => emit({ event_type: 'cloud_transcription_status', state: 'bogus' }));
    expect(result.current.state?.status.state).toBe('streaming');
    act(() => emit({ event_type: 'cloud_transcription_status', state: 'fallback', provider: 'deepgram', tier: 'streaming', reason: 'Deepgram closed the connection.' }));
    expect(result.current.state?.status.reason).toBe('Deepgram closed the connection.');
  });

  it('hydrates again whenever the socket reconnects', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    const before = fetchMock.mock.calls.length;
    serverState = cloudState({ enabled: true, acknowledged: true });
    await act(async () => {
      for (const handler of sockets[0].connectHandlers) handler();
    });
    await waitFor(() => expect(result.current.state?.enabled).toBe(true));
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it('reports a load failure and recovers on retry', async () => {
    fetchMock.mockReturnValueOnce(Promise.resolve(new Response('no', { status: 503 })));
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.loadError).toBe('Could not load the cloud transcription settings.'));
    await act(async () => {
      await result.current.retry();
    });
    expect(result.current.loadError).toBeNull();
    expect(result.current.state).toEqual(serverState);
  });

  it('applies the returned state after a settings update and shows backend refusals', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: 'Add a Deepgram API key first.' }, 409));
    let accepted = true;
    await act(async () => {
      accepted = await result.current.update({ enabled: true, acknowledge_disclosure: true });
    });
    expect(accepted).toBe(false);
    expect(result.current.actionError).toBe('Add a Deepgram API key first.');
    expect(result.current.state?.enabled).toBe(false);
    fetchMock.mockReturnValueOnce(jsonResponse(cloudState({ enabled: true, acknowledged: true })));
    await act(async () => {
      accepted = await result.current.update({ enabled: true, acknowledge_disclosure: true });
    });
    expect(accepted).toBe(true);
    expect(result.current.actionError).toBeNull();
    expect(result.current.state?.enabled).toBe(true);
    expect(result.current.busy).toBe(false);
  });

  it('uses a generic message for unexpected failures', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    fetchMock.mockReturnValueOnce(Promise.reject(new TypeError('network down')));
    await act(async () => {
      await result.current.update({ enabled: false });
    });
    expect(result.current.actionError).toBe('That did not work. Try again.');
  });

  it('saves and removes keys, and clears the previous check result', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    fetchMock.mockReturnValueOnce(jsonResponse({ ok: true, message: 'Connected to Deepgram. No meeting audio was sent.' }));
    await act(async () => {
      await result.current.check('deepgram');
    });
    expect(result.current.checkResult).toEqual({ ok: true, message: 'Connected to Deepgram. No meeting audio was sent.' });
    const withKey = cloudState({ providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] });
    fetchMock.mockReturnValueOnce(jsonResponse(withKey));
    await act(async () => {
      await result.current.saveKey('deepgram', 'dg-key-123456');
    });
    expect(result.current.checkResult).toBeNull();
    expect(result.current.state?.providers[0].has_key).toBe(true);
    expect(String(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0])).toContain('/keys/deepgram');
    fetchMock.mockReturnValueOnce(jsonResponse(cloudState()));
    await act(async () => {
      await result.current.removeKey('deepgram');
    });
    expect(result.current.state?.providers[0].has_key).toBe(false);
    expect((fetchMock.mock.calls[fetchMock.mock.calls.length - 1][1] as RequestInit).method).toBe('DELETE');
  });

  it('shows a check failure from the backend as an error, not a result', async () => {
    const { result } = renderHook(() => useCloudTranscription(8123));
    await waitFor(() => expect(result.current.state).not.toBeNull());
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: 'nope' }, 500));
    await act(async () => {
      await result.current.check('assemblyai');
    });
    expect(result.current.checkResult).toBeNull();
    expect(result.current.actionError).toBe('nope');
  });
});
