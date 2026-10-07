// web-components/TranscriptionWidget/src/bridge/audioFileUploadBridge.ts

import { createSwiftBridge, missingHandlerLogger } from '@shared/swiftBridge';
import { AUDIO_UPLOAD_PROTOCOL_VERSION } from './audioFileUploadTypes';
import type { AudioFileUploadBridgeEvent, AudioFileUploadBridgeIntent } from './audioFileUploadTypes';

type EventListener = (event: AudioFileUploadBridgeEvent) => void;

let eventListener: EventListener | null = null;
const pendingEvents: AudioFileUploadBridgeEvent[] = [];

function dispatchEvent(event: AudioFileUploadBridgeEvent): void {
  if (eventListener) {
    eventListener(event);
  } else {
    pendingEvents.push(event);
  }
}

window.basilAudioFileUpload = { onEvent: dispatchEvent };

export function onAudioFileUploadEvent(listener: EventListener): () => void {
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

const swiftBridge = createSwiftBridge<AudioFileUploadBridgeIntent>('audioFileUploadBridge', {
  onMissing: missingHandlerLogger('warn', '[audioFileUploadBridge] no native handler registered; intent dropped'),
});

function postToSwift(intent: AudioFileUploadBridgeIntent): void {
  swiftBridge.post(intent);
}

export function reportAudioUploadReady(): void {
  postToSwift({ type: 'reactReady', protocolVersion: AUDIO_UPLOAD_PROTOCOL_VERSION });
}
export function selectAudioFile(): void {
  postToSwift({ type: 'selectAudioFile' });
}
export function clearSelectedFile(): void {
  postToSwift({ type: 'clearSelectedFile' });
}
export function setDescription(value: string): void {
  postToSwift({ type: 'setDescription', value });
}
export function setLanguage(value: string): void {
  postToSwift({ type: 'setLanguage', value });
}
export function uploadAudioFile(): void {
  postToSwift({ type: 'upload' });
}
export function copyTranscriptionResult(): void {
  postToSwift({ type: 'copyTranscriptionResult' });
}
export function dismissAudioUploadError(): void {
  postToSwift({ type: 'dismissError' });
}
export function cancelAudioUpload(): void {
  postToSwift({ type: 'cancel' });
}
export function minimizeAudioUpload(): void {
  postToSwift({ type: 'minimize' });
}
export function collapseAudioUpload(): void {
  postToSwift({ type: 'collapse' });
}
export function expandAudioUpload(): void {
  postToSwift({ type: 'expand' });
}
