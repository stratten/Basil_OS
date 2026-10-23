import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import type { WSEvent } from '../types';

export type AgentTaskEventSubscriber = (handler: (event: WSEvent) => void) => () => void;

export class WebSocketManager extends ReconnectingWebSocket<WSEvent> {}

export const wsManager = new WebSocketManager();
