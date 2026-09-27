// web-components/AssistantSession/src/bridge/assistantSessionBridge.ts

import { PROTOCOL_VERSION } from './types';
import type {
  AssistantSessionBridgeEvent,
  AssistantSessionBridgeIntent,
  AssistantSessionInputMode,
  AssistantSessionModelInfo,
  AssistantSessionModelPickerAnchorRect,
} from './types';

type EventListener = (event: AssistantSessionBridgeEvent) => void;
type MeterListener = (audioLevel: number) => void;

let eventListener: EventListener | null = null;
let meterListener: MeterListener | null = null;
const pendingEvents: AssistantSessionBridgeEvent[] = [];

function dispatchEvent(event: AssistantSessionBridgeEvent): void {
  if (event.type === 'meter') {
    meterListener?.(event.audioLevel);
    return;
  }
  if (eventListener) {
    eventListener(event);
  } else {
    pendingEvents.push(event);
  }
}

window.basilAssistantSession = { onEvent: dispatchEvent };

/** Registers the single reducer-feeding listener. Returns an unsubscribe function. */
export function onAssistantSessionEvent(listener: EventListener): () => void {
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

/** Registers the bubble's high-frequency meter listener, kept off the revisioned event path. */
export function onAssistantSessionMeter(listener: MeterListener): () => void {
  meterListener = listener;
  return () => {
    if (meterListener === listener) {
      meterListener = null;
    }
  };
}

function postToSwift(intent: AssistantSessionBridgeIntent): void {
  const handler = window.webkit?.messageHandlers?.assistantSessionBridge;
  if (!handler) {
    // eslint-disable-next-line no-console
    console.warn('[assistantSessionBridge] no native handler registered; intent dropped', intent);
    return;
  }
  handler.postMessage(intent);
}

export function reportReady(): void {
  postToSwift({ type: 'reactReady', protocolVersion: PROTOCOL_VERSION });
}

export function cancelOperation(): void {
  postToSwift({ type: 'cancelOperation' });
}
export function minimizeWidget(): void {
  postToSwift({ type: 'minimizeWidget' });
}
export function toggleResultCollapse(): void {
  postToSwift({ type: 'toggleResultCollapse' });
}
export function switchInputMode(mode: AssistantSessionInputMode): void {
  postToSwift({ type: 'switchInputMode', mode });
}
export function submitTypedInstruction(text: string): void {
  postToSwift({ type: 'submitTypedInstruction', text });
}
export function stopRecording(): void {
  postToSwift({ type: 'stopRecording' });
}
export function selectModel(modelId: string): void {
  postToSwift({ type: 'selectModel', modelId });
}
export function showNativeModelPicker(
  models: AssistantSessionModelInfo[],
  selectedModelId: string | null,
  anchorRect: AssistantSessionModelPickerAnchorRect,
): void {
  postToSwift({ type: 'showNativeModelPicker', models, selectedModelId, anchorRect });
}
export function enterEditMode(): void {
  postToSwift({ type: 'enterEditMode' });
}
export function cancelEditMode(): void {
  postToSwift({ type: 'cancelEditMode' });
}
export function applyEdits(content: string): void {
  postToSwift({ type: 'applyEdits', content });
}
export function saveAsSample(content: string | null): void {
  postToSwift({ type: 'saveAsSample', content });
}
export function enterVoiceRefinement(): void {
  postToSwift({ type: 'enterVoiceRefinement' });
}
export function enterTypedRefinement(): void {
  postToSwift({ type: 'enterTypedRefinement' });
}
export function cancelTypedRefinement(): void {
  postToSwift({ type: 'cancelTypedRefinement' });
}
export function submitTypedRefinement(text: string): void {
  postToSwift({ type: 'submitTypedRefinement', text });
}
export function stopRefinementRecording(): void {
  postToSwift({ type: 'stopRefinementRecording' });
}
export function copyRichText(): void {
  postToSwift({ type: 'copyRichText' });
}
export function copyMarkdown(): void {
  postToSwift({ type: 'copyMarkdown' });
}
export function openHistory(): void {
  postToSwift({ type: 'openHistory' });
}
export function requestResize(width: number, height: number): void {
  postToSwift({ type: 'requestResize', width, height });
}
