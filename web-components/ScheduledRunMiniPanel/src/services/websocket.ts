import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import type { WSEvent } from '../types';

/**
 * The panel is usually open only while a run is in flight, so reconnects use a fixed 2s delay instead of an exponential ramp.
 */
class WSManager extends ReconnectingWebSocket<WSEvent> {
  constructor() {
    super({ initialReconnectDelayMs: 2000, maxReconnectDelayMs: 2000, logLabel: '[ScheduledRun WS]' });
  }
}

export const wsManager = new WSManager();
