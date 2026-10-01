import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReconnectingWebSocket } from './reconnectingWebSocket';

type TestEvent = { event_type?: string; value?: number };

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(payload: string): void {
    this.sent.push(payload);
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  simulateOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(data: unknown): void {
    this.onmessage?.({ data });
  }
}

class TestSocket extends ReconnectingWebSocket<TestEvent> {
  send(payload: Record<string, unknown>): boolean {
    return this.sendJson(payload);
  }
}

function latestSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!socket) throw new Error('No socket was created');
  return socket;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ReconnectingWebSocket', () => {
  it('opens one socket, reports state transitions, and runs connect handlers on open', () => {
    const manager = new TestSocket();
    const states: string[] = [];
    const onConnect = vi.fn();
    manager.subscribeConnectionState((state) => states.push(state));
    manager.onConnect(onConnect);

    manager.connect('ws://127.0.0.1:8000/ws');
    manager.connect('ws://127.0.0.1:8000/ws');
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(latestSocket().url).toBe('ws://127.0.0.1:8000/ws');

    latestSocket().simulateOpen();
    manager.connect('ws://127.0.0.1:8000/ws');
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(onConnect).toHaveBeenCalledTimes(1);
    expect(states).toEqual(['closed', 'connecting', 'open']);
    expect(manager.isConnected).toBe(true);
  });

  it('delivers event_type messages and ignores malformed, empty, null, and untyped frames', () => {
    const manager = new TestSocket();
    const handler = vi.fn();
    manager.subscribe(handler);
    manager.connect('ws://test/ws');
    const socket = latestSocket();
    socket.simulateOpen();

    socket.simulateMessage('not json');
    socket.simulateMessage('');
    socket.simulateMessage('null');
    socket.simulateMessage(JSON.stringify({ value: 1 }));
    socket.simulateMessage(JSON.stringify({ event_type: 'agent_task_artifact', value: 2 }));

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith({ event_type: 'agent_task_artifact', value: 2 });
  });

  it('stops delivering to unsubscribed event and connect handlers', () => {
    const manager = new TestSocket();
    const handler = vi.fn();
    const onConnect = vi.fn();
    const unsubscribe = manager.subscribe(handler);
    const removeConnect = manager.onConnect(onConnect);
    unsubscribe();
    removeConnect();

    manager.connect('ws://test/ws');
    latestSocket().simulateOpen();
    latestSocket().simulateMessage(JSON.stringify({ event_type: 'agent_task_artifact' }));

    expect(handler).not.toHaveBeenCalled();
    expect(onConnect).not.toHaveBeenCalled();
  });

  it('reconnects with exponential backoff capped at the maximum delay', () => {
    const manager = new TestSocket({ initialReconnectDelayMs: 1000, maxReconnectDelayMs: 3000 });
    manager.connect('ws://test/ws');

    latestSocket().close();
    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);

    latestSocket().close();
    vi.advanceTimersByTime(1999);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);

    latestSocket().close();
    vi.advanceTimersByTime(3000);
    expect(FakeWebSocket.instances).toHaveLength(4);

    latestSocket().close();
    vi.advanceTimersByTime(3000);
    expect(FakeWebSocket.instances).toHaveLength(5);
  });

  it('resets the backoff after a successful open', () => {
    const manager = new TestSocket();
    manager.connect('ws://test/ws');

    latestSocket().close();
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(2);

    latestSocket().simulateOpen();
    latestSocket().close();
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('uses a fixed delay when the initial and maximum delays match', () => {
    const manager = new TestSocket({ initialReconnectDelayMs: 2000, maxReconnectDelayMs: 2000 });
    manager.connect('ws://test/ws');

    latestSocket().close();
    vi.advanceTimersByTime(1999);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);

    latestSocket().close();
    vi.advanceTimersByTime(2000);
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('does not reconnect after disconnect, including a pending reconnect', () => {
    const manager = new TestSocket();
    const states: string[] = [];
    manager.subscribeConnectionState((state) => states.push(state));
    manager.connect('ws://test/ws');
    latestSocket().simulateOpen();

    manager.disconnect();
    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(manager.isConnected).toBe(false);
    expect(states[states.length - 1]).toBe('closed');

    manager.connect('ws://test/ws');
    latestSocket().close();
    manager.disconnect();
    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('ignores messages and closes from a replaced socket', () => {
    const manager = new TestSocket();
    const handler = vi.fn();
    manager.subscribe(handler);
    manager.connect('ws://test/ws');
    const first = latestSocket();
    first.simulateOpen();

    manager.disconnect();
    manager.connect('ws://test/ws');
    const second = latestSocket();
    expect(second).not.toBe(first);

    first.simulateMessage(JSON.stringify({ event_type: 'stale' }));
    first.onclose?.();
    second.simulateOpen();
    second.simulateMessage(JSON.stringify({ event_type: 'fresh' }));
    vi.advanceTimersByTime(60000);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith({ event_type: 'fresh' });
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('schedules a reconnect and logs once when the WebSocket constructor throws', () => {
    let attempts = 0;
    class ThrowingOnceWebSocket extends FakeWebSocket {
      constructor(url: string) {
        attempts += 1;
        if (attempts === 1) throw new Error('refused');
        super(url);
      }
    }
    vi.stubGlobal('WebSocket', ThrowingOnceWebSocket);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const manager = new TestSocket({ logLabel: '[Test WS]' });

    manager.connect('ws://test/ws');
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalledWith('[Test WS] Connection failed:', expect.any(Error));

    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('sends JSON only while open and reports send failures', () => {
    const manager = new TestSocket();
    expect(manager.send({ type: 'x' })).toBe(false);

    manager.connect('ws://test/ws');
    expect(manager.send({ type: 'x' })).toBe(false);

    const socket = latestSocket();
    socket.simulateOpen();
    expect(manager.send({ type: 'x' })).toBe(true);
    expect(socket.sent).toEqual([JSON.stringify({ type: 'x' })]);

    socket.send = () => {
      throw new Error('closed mid-send');
    };
    expect(manager.send({ type: 'y' })).toBe(false);
  });
});
