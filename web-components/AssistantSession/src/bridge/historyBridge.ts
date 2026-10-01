// web-components/AssistantSession/src/bridge/historyBridge.ts

import type { AssistantOutputHistoryBridgeEvent, AssistantOutputHistoryBridgeIntent, HistoryRefinementInput } from './historyTypes';

type EventListener = (event: AssistantOutputHistoryBridgeEvent) => void;

let eventListener: EventListener | null = null;
const pendingEvents: AssistantOutputHistoryBridgeEvent[] = [];

window.basilAssistantOutputHistory = {
  onEvent: (event) => {
    if (eventListener) {
      eventListener(event);
    } else {
      pendingEvents.push(event);
    }
  },
};

export function onHistoryEvent(listener: EventListener): () => void {
  eventListener = listener;
  if (pendingEvents.length > 0) {
    const queued = pendingEvents.splice(0, pendingEvents.length);
    queued.forEach((event) => listener(event));
  }
  return () => {
    if (eventListener === listener) {
      eventListener = null;
    }
  };
}

function postToSwift(intent: AssistantOutputHistoryBridgeIntent): void {
  const handler = window.webkit?.messageHandlers?.assistantOutputHistoryBridge;
  if (!handler) {
    // eslint-disable-next-line no-console
    console.warn('[historyBridge] no native handler registered; intent dropped', intent);
    return;
  }
  handler.postMessage(intent);
}

export function reportHistoryReady(): void {
  postToSwift({ type: 'historyWidgetReady' });
}
export function closeWindow(): void {
  postToSwift({ type: 'closeWindow' });
}
export function minimizeWindow(): void {
  postToSwift({ type: 'minimizeWindow' });
}
export function toggleChromeCollapse(collapsed: boolean): void {
  postToSwift({ type: 'toggleChromeCollapse', collapsed });
}
export function refineFromHistory(assistantOutputId: number, input: HistoryRefinementInput): void {
  postToSwift({ type: 'refineFromHistory', assistantOutputId, input });
}
export function copyHistoryRichText(content: string): void {
  postToSwift({ type: 'copyHistoryRichText', content });
}
export function copyHistoryMarkdown(content: string): void {
  postToSwift({ type: 'copyHistoryMarkdown', content });
}
