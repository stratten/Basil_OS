import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceAdvice } from './resourceAdviceTypes';

const { sockets, FakeSocket } = vi.hoisted(() => {
  const created: Array<{
    handlers: Array<(frame: { event_type: string } & Record<string, unknown>) => void>;
    connectHandlers: Array<() => void>;
    url: string;
    disconnected: boolean;
    emit: (frame: { event_type: string } & Record<string, unknown>) => void;
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
    emit(frame: { event_type: string } & Record<string, unknown>) {
      for (const handler of this.handlers) handler(frame);
    }
  }
  return { sockets: created, FakeSocket: HoistedFakeSocket };
});

vi.mock('@shared/websocket/reconnectingWebSocket', () => ({ ReconnectingWebSocket: FakeSocket }));

import { useResourceAdvice } from './useResourceAdvice';

const lag: ResourceAdvice = { id: 'transcription_lag', severity: 'warning', title: 'Transcription is behind the meeting', detail: 'detail', action: 'open_settings', raised_at: 10 };
const heat: ResourceAdvice = { id: 'thermal', severity: 'warning', title: 'Your Mac is running hot', detail: 'detail', action: 'none', raised_at: 12 };

function respond(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

let fetchMock: ReturnType<typeof vi.fn>;
let serverState: { revision: number; advice: ResourceAdvice[] };

beforeEach(() => {
  sockets.length = 0;
  serverState = { revision: 1, advice: [lag] };
  fetchMock = vi.fn((url: string) => {
    if (url.endsWith('/client-state')) return respond(serverState);
    if (url.endsWith('/dismiss')) return respond({ revision: 2, advice: [] });
    return respond(serverState);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('useResourceAdvice', () => {
  it('stays empty and opens nothing when not recording or without a port', () => {
    const idle = renderHook(() => useResourceAdvice({ port: 8123, recording: false, thermalState: 'serious' }));
    const noPort = renderHook(() => useResourceAdvice({ port: 0, recording: true, thermalState: 'serious' }));
    expect(idle.result.current.advice).toEqual([]);
    expect(noPort.result.current.advice).toEqual([]);
    expect(sockets).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('hydrates from the backend and listens on the shared socket while recording', async () => {
    const { result } = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: null }));
    await waitFor(() => expect(result.current.advice).toEqual([lag]));
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8123/meetings/resource-advice', expect.anything());
    expect(sockets).toHaveLength(1);
    expect(sockets[0].url).toBe('ws://127.0.0.1:8123/ws');
  });

  it('applies newer frames, ignores older and unrelated ones, and rehydrates on reconnect', async () => {
    const { result } = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: null }));
    await waitFor(() => expect(result.current.advice).toEqual([lag]));
    act(() => sockets[0].emit({ event_type: 'resource_advice', revision: 2, advice: [lag, heat] }));
    expect(result.current.advice).toEqual([lag, heat]);
    act(() => sockets[0].emit({ event_type: 'resource_advice', revision: 2, advice: [] }));
    act(() => sockets[0].emit({ event_type: 'resource_advice', revision: 1, advice: [] }));
    act(() => sockets[0].emit({ event_type: 'meeting_companion_status', revision: 9, advice: [] }));
    act(() => sockets[0].emit({ event_type: 'resource_advice', revision: 'x', advice: [] }));
    expect(result.current.advice).toEqual([lag, heat]);
    serverState = { revision: 0, advice: [] };
    await act(async () => sockets[0].connectHandlers[0]());
    await waitFor(() => expect(result.current.advice).toEqual([]));
    act(() => sockets[0].emit({ event_type: 'resource_advice', revision: 1, advice: [heat] }));
    expect(result.current.advice).toEqual([heat]);
  });

  it('keeps the advice hidden when the backend cannot be reached', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error('offline')));
    const { result } = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: null }));
    await act(async () => undefined);
    expect(result.current.advice).toEqual([]);
  });

  it('clears the advice and closes the socket when the recording stops', async () => {
    const { result, rerender } = renderHook((props: { recording: boolean }) => useResourceAdvice({ port: 8123, recording: props.recording, thermalState: null }), { initialProps: { recording: true } });
    await waitFor(() => expect(result.current.advice).toEqual([lag]));
    rerender({ recording: false });
    expect(result.current.advice).toEqual([]);
    expect(sockets[0].disconnected).toBe(true);
  });

  it('reports a valid thermal state at once and every minute, and never an unknown one', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const reporting = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: 'serious' }));
    const puts = () => fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT');
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(JSON.parse((puts()[0][1] as RequestInit).body as string)).toEqual({ thermal_state: 'serious' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(puts()).toHaveLength(2);
    reporting.unmount();
    sockets.length = 0;
    fetchMock.mockClear();
    renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: 'lava' }));
    renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: undefined }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(puts()).toHaveLength(0);
  });

  it('sends a new thermal state as soon as it changes', async () => {
    const { rerender } = renderHook((props: { thermal: string }) => useResourceAdvice({ port: 8123, recording: true, thermalState: props.thermal }), { initialProps: { thermal: 'fair' } });
    const bodies = () => fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT').map(([, init]) => JSON.parse((init as RequestInit).body as string).thermal_state);
    await waitFor(() => expect(bodies()).toEqual(['fair']));
    rerender({ thermal: 'critical' });
    await waitFor(() => expect(bodies()).toEqual(['fair', 'critical']));
  });

  it('dismisses through the backend and shows the answer', async () => {
    const { result } = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: null }));
    await waitFor(() => expect(result.current.advice).toEqual([lag]));
    await act(async () => result.current.dismiss('transcription_lag'));
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8123/meetings/resource-advice/transcription_lag/dismiss', expect.objectContaining({ method: 'POST' }));
    expect(result.current.advice).toEqual([]);
  });

  it('leaves the advice showing when a dismissal fails', async () => {
    const { result } = renderHook(() => useResourceAdvice({ port: 8123, recording: true, thermalState: null }));
    await waitFor(() => expect(result.current.advice).toEqual([lag]));
    fetchMock.mockImplementation(() => respond({ detail: 'no' }, 404));
    await act(async () => result.current.dismiss('transcription_lag'));
    expect(result.current.advice).toEqual([lag]);
  });
});
