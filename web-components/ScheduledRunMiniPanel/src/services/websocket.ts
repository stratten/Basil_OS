import type { WSEvent } from '../types';

type Listener = (event: WSEvent) => void;

/**
 * Minimal, dependency-free WS subscription manager for the mini panel.
 * Mirrors the shape of AgentTaskResult/src/services/websocket.ts but
 * without all the agent-task-specific machinery — this panel only
 * cares about scheduled_agent_task_run_started / agent_progress_update /
 * scheduled_agent_task_run_completed for rows it owns.
 *
 * Reconnect is intentionally simple: a fixed 2s backoff. The panel is
 * almost always short-lived (open while a run is in flight, close when
 * empty), so an exponential ramp would never get past the first slot.
 */
class WSManager {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private url: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connectListeners = new Set<() => void>();

  connect(url: string) {
    this.url = url;
    this.openSocket();
  }

  private openSocket() {
    if (!this.url) return;
    try {
      const ws = new WebSocket(this.url);
      this.socket = ws;
      ws.onopen = () => {
        for (const cb of this.connectListeners) cb();
      };
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data) as WSEvent;
          for (const l of this.listeners) l(data);
        } catch {
          // Ignore non-JSON frames; the backend never sends binary on this socket.
        }
      };
      ws.onclose = () => {
        this.socket = null;
        this.scheduleReconnect();
      };
      ws.onerror = () => {
        try { ws.close(); } catch { /* noop */ }
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, 2000);
  }

  subscribe(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  onConnect(cb: () => void) {
    this.connectListeners.add(cb);
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      cb();
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try { this.socket?.close(); } catch { /* noop */ }
    this.socket = null;
  }
}

export const wsManager = new WSManager();
