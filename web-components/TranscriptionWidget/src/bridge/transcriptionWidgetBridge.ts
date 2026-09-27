// web-components/TranscriptionWidget/src/bridge/transcriptionWidgetBridge.ts

import { PROTOCOL_VERSION } from './types';
import type { TranscriptionBridgeEvent, TranscriptionBridgeIntent, TranscriptionModelInfo } from './types';
import { publishTranscriptionMeter } from './transcriptionMeterStore';

type EventListener = (event: TranscriptionBridgeEvent) => void;

let eventListener: EventListener | null = null;
const pendingEvents: TranscriptionBridgeEvent[] = [];

function dispatchEvent(event: TranscriptionBridgeEvent): void {
  if (event.type === 'meter') {
    publishTranscriptionMeter(event.audioLevel);
    return;
  }
  if (eventListener) {
    eventListener(event);
  } else {
    pendingEvents.push(event);
  }
}

window.basilTranscriptionWidget = { onEvent: dispatchEvent };

/** Registers the single reducer-feeding listener. Returns an unsubscribe function. */
export function onTranscriptionEvent(listener: EventListener): () => void {
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

function postToSwift(intent: TranscriptionBridgeIntent): void {
  const handler = window.webkit?.messageHandlers?.transcriptionWidgetBridge;
  if (!handler) {
    // eslint-disable-next-line no-console
    console.warn('[transcriptionWidgetBridge] no native handler registered; intent dropped', intent);
    return;
  }
  handler.postMessage(intent);
}

export function reportReady(): void {
  postToSwift({ type: 'reactReady', protocolVersion: PROTOCOL_VERSION });
}
export function toggleRecording(): void {
  postToSwift({ type: 'toggleRecording' });
}
export function cancelRecording(): void {
  postToSwift({ type: 'cancelRecording' });
}
export function toggleMinimizedState(): void {
  postToSwift({ type: 'toggleMinimizedState' });
}
export function closeWidget(): void {
  postToSwift({ type: 'close' });
}
export function clearTranscription(): void {
  postToSwift({ type: 'clearTranscription' });
}
export function copyToClipboard(): void {
  postToSwift({ type: 'copyToClipboard' });
}
export function selectTranscriptionModel(modelId: string): void {
  postToSwift({ type: 'selectTranscriptionModel', modelId });
}
export function showTranscriptionModelMenu(
  models: TranscriptionModelInfo[],
  selectedModelId: string,
  anchorRect: { x: number; y: number; width: number; height: number },
): void {
  postToSwift({ type: 'showTranscriptionModelMenu', models, selectedModelId, anchorRect });
}
export function openSystemMicrophoneSettings(): void {
  postToSwift({ type: 'openSystemMicrophoneSettings' });
}
export function showTranscriptionError(): void {
  postToSwift({ type: 'showErrorPopover' });
}
export function requestResize(width: number, height: number): void {
  postToSwift({ type: 'requestResize', width, height });
}
