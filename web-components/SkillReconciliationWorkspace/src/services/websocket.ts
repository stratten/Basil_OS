import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import type { WSEvent } from '../types';

export class WebSocketManager extends ReconnectingWebSocket<WSEvent> {}

export const wsManager = new WebSocketManager();
