export type WebSocketConnectionState = 'connecting' | 'open' | 'closed';

/**
 * Whether the backend is actually answering: 'stale' means the socket is open and heartbeats had been arriving on it, but none has for staleAfterMs.
 * A frozen backend keeps its TCP socket open, so socket state alone cannot show it.
 */
export type BackendLivenessState = 'connecting' | 'live' | 'stale' | 'disconnected';

export const BACKEND_HEARTBEAT_EVENT_TYPE = 'backend_heartbeat';
const SUBSCRIBE_HEARTBEAT_MESSAGE = { type: 'subscribe_backend_heartbeat' };

export interface ReconnectingWebSocketOptions {
  initialReconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
  logLabel?: string;
  staleAfterMs?: number;
  livenessCheckIntervalMs?: number;
}

type EventHandler<TEvent> = (event: TEvent) => void;
type ConnectHandler = () => void;
type ConnectionStateHandler = (state: WebSocketConnectionState) => void;
type LivenessHandler = (state: BackendLivenessState) => void;

/**
 * Client for the backend's shared /ws event bus. The reconnect delay doubles after each attempt up to maxReconnectDelayMs; pass equal delays for a fixed backoff.
 */
export class ReconnectingWebSocket<TEvent extends { event_type?: string }> {
  protected ws: WebSocket | null = null;
  private url = '';
  private handlers: EventHandler<TEvent>[] = [];
  private connectHandlers: ConnectHandler[] = [];
  private connectionStateHandlers: ConnectionStateHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly initialReconnectDelayMs: number;
  private readonly maxReconnectDelayMs: number;
  private readonly logLabel: string;
  private reconnectDelay: number;
  private shouldReconnect = false;
  private connectionState: WebSocketConnectionState = 'closed';
  private livenessHandlers: LivenessHandler[] = [];
  private livenessState: BackendLivenessState = 'connecting';
  private lastHeartbeatAt: number | null = null;
  private livenessTimer: ReturnType<typeof setInterval> | null = null;
  private hasAttemptedConnection = false;
  private readonly staleAfterMs: number;
  private readonly livenessCheckIntervalMs: number;

  constructor(options: ReconnectingWebSocketOptions = {}) {
    this.initialReconnectDelayMs = options.initialReconnectDelayMs ?? 1000;
    this.maxReconnectDelayMs = options.maxReconnectDelayMs ?? 30000;
    this.logLabel = options.logLabel ?? '[WS]';
    this.reconnectDelay = this.initialReconnectDelayMs;
    this.staleAfterMs = options.staleAfterMs ?? 10_000;
    this.livenessCheckIntervalMs = options.livenessCheckIntervalMs ?? 1_000;
  }

  connect(url: string): void {
    this.url = url;
    this.shouldReconnect = true;
    this.hasAttemptedConnection = true;
    this.startLivenessTimer();
    this.doConnect();
  }

  private computeLiveness(): BackendLivenessState {
    if (this.connectionState === 'connecting') return 'connecting';
    if (this.connectionState === 'closed') return this.hasAttemptedConnection ? 'disconnected' : 'connecting';
    if (this.lastHeartbeatAt !== null && Date.now() - this.lastHeartbeatAt > this.staleAfterMs) return 'stale';
    return 'live';
  }

  private refreshLiveness(): void {
    const next = this.computeLiveness();
    if (next === this.livenessState) return;
    this.livenessState = next;
    for (const handler of this.livenessHandlers) handler(next);
  }

  private startLivenessTimer(): void {
    if (this.livenessTimer) return;
    this.livenessTimer = setInterval(() => this.refreshLiveness(), this.livenessCheckIntervalMs);
  }

  private stopLivenessTimer(): void {
    if (!this.livenessTimer) return;
    clearInterval(this.livenessTimer);
    this.livenessTimer = null;
  }

  private setConnectionState(state: WebSocketConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    for (const handler of this.connectionStateHandlers) handler(state);
    this.refreshLiveness();
  }

  private doConnect(): void {
    if (!this.shouldReconnect || !this.url) return;
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    this.setConnectionState('connecting');
    try {
      const socket = new WebSocket(this.url);
      this.ws = socket;
      socket.onopen = () => {
        if (this.ws !== socket) return;
        this.reconnectDelay = this.initialReconnectDelayMs;
        this.lastHeartbeatAt = null;
        this.setConnectionState('open');
        this.sendJson(SUBSCRIBE_HEARTBEAT_MESSAGE);
        for (const handler of this.connectHandlers) handler();
      };
      socket.onmessage = (event) => {
        if (this.ws !== socket) return;
        try {
          const data = JSON.parse(event.data) as TEvent;
          if (data.event_type === BACKEND_HEARTBEAT_EVENT_TYPE) {
            this.lastHeartbeatAt = Date.now();
            this.refreshLiveness();
            return;
          }
          if (data.event_type) {
            for (const handler of this.handlers) handler(data);
          }
        } catch {
          // Ignore malformed and non-JSON frames without disrupting later events.
        }
      };
      socket.onclose = () => {
        if (this.ws !== socket) return;
        this.ws = null;
        this.lastHeartbeatAt = null;
        this.setConnectionState('closed');
        this.scheduleReconnect();
      };
      socket.onerror = () => socket.close();
    } catch (error) {
      console.error(`${this.logLabel} Connection failed:`, error);
      this.ws = null;
      this.setConnectionState('closed');
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelayMs);
      this.doConnect();
    }, this.reconnectDelay);
  }

  protected sendJson(payload: Record<string, unknown>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }

  subscribe(handler: EventHandler<TEvent>): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((item) => item !== handler);
    };
  }

  onConnect(handler: ConnectHandler): () => void {
    this.connectHandlers.push(handler);
    return () => {
      this.connectHandlers = this.connectHandlers.filter((item) => item !== handler);
    };
  }

  subscribeConnectionState(handler: ConnectionStateHandler): () => void {
    this.connectionStateHandlers.push(handler);
    handler(this.connectionState);
    return () => {
      this.connectionStateHandlers = this.connectionStateHandlers.filter((item) => item !== handler);
    };
  }

  subscribeLiveness(handler: LivenessHandler): () => void {
    this.livenessHandlers.push(handler);
    handler(this.livenessState);
    return () => {
      this.livenessHandlers = this.livenessHandlers.filter((item) => item !== handler);
    };
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.stopLivenessTimer();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.ws;
    this.ws = null;
    socket?.close();
    this.setConnectionState('closed');
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
