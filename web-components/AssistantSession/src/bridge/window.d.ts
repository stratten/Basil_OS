import type { AssistantSessionBridgeEvent } from './types';
import type { AssistantOutputHistoryBridgeEvent } from './historyTypes';

declare global {
  interface Window {
    basilAssistantSession?: {
      onEvent: (event: AssistantSessionBridgeEvent) => void;
    };
    basilAssistantOutputHistory?: {
      onEvent: (event: AssistantOutputHistoryBridgeEvent) => void;
    };
  }
}

export {};
