import type { WSEvent } from '../types';

type EventHandler = (event: WSEvent) => void;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private url: string = '';
  private handlers: EventHandler[] = [];
  private connectHandlers: (() => void)[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = false;

  connect(url: string) {
    this.shouldReconnect = true;
    this.url = url;
    this.doConnect();
  }

  private doConnect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[WS] Connected');
        this.reconnectDelay = 1000;
        for (const handler of this.connectHandlers) handler();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSEvent;
          if (data.event_type) {
            for (const handler of this.handlers) {
              handler(data);
            }
          }
        } catch {
          // Binary or non-JSON message, ignore
        }
      };

      this.ws.onclose = () => {
        if (this.shouldReconnect) {
          console.log('[WS] Disconnected, scheduling reconnect');
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        console.log('[WS] Error');
        this.ws?.close();
      };
    } catch (err) {
      console.error('[WS] Connection failed:', err);
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.doConnect();
    }, this.reconnectDelay);
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter(h => h !== handler);
    };
  }

  onConnect(handler: () => void): () => void {
    this.connectHandlers.push(handler);
    return () => {
      this.connectHandlers = this.connectHandlers.filter(h => h !== handler);
    };
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const wsManager = new WebSocketManager();
