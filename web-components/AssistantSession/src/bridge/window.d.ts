import type { AssistantSessionBridgeEvent, AssistantSessionBridgeIntent } from './types';
import type { AssistantOutputHistoryBridgeEvent, AssistantOutputHistoryBridgeIntent } from './historyTypes';

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        assistantSessionBridge?: {
          postMessage: (message: AssistantSessionBridgeIntent) => void;
        };
        assistantOutputHistoryBridge?: {
          postMessage: (message: AssistantOutputHistoryBridgeIntent) => void;
        };
      };
    };
    basilAssistantSession?: {
      onEvent: (event: AssistantSessionBridgeEvent) => void;
    };
    basilAssistantOutputHistory?: {
      onEvent: (event: AssistantOutputHistoryBridgeEvent) => void;
    };
  }
}

export {};
