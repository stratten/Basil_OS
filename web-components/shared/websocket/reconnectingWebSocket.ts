export type WebSocketConnectionState = 'connecting' | 'open' | 'closed';

export interface ReconnectingWebSocketOptions {
  initialReconnectDelayMs?: number;
  maxReconnectDelayMs?: number;
  logLabel?: string;
}

type EventHandler<TEvent> = (event: TEvent) => void;
type ConnectHandler = () => void;
type ConnectionStateHandler = (state: WebSocketConnectionState) => void;

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

  constructor(options: ReconnectingWebSocketOptions = {}) {
    this.initialReconnectDelayMs = options.initialReconnectDelayMs ?? 1000;
    this.maxReconnectDelayMs = options.maxReconnectDelayMs ?? 30000;
    this.logLabel = options.logLabel ?? '[WS]';
    this.reconnectDelay = this.initialReconnectDelayMs;
  }

  connect(url: string): void {
    this.url = url;
    this.shouldReconnect = true;
    this.doConnect();
  }

  private setConnectionState(state: WebSocketConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    for (const handler of this.connectionStateHandlers) handler(state);
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
        this.setConnectionState('open');
        for (const handler of this.connectHandlers) handler();
      };
      socket.onmessage = (event) => {
        if (this.ws !== socket) return;
        try {
          const data = JSON.parse(event.data) as TEvent;
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

  disconnect(): void {
    this.shouldReconnect = false;
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
