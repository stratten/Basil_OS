import type { TranscriptionBridgeEvent, TranscriptionBridgeIntent } from './types';
import type { AudioFileUploadBridgeEvent, AudioFileUploadBridgeIntent } from './audioFileUploadTypes';

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        transcriptionWidgetBridge?: {
          postMessage: (message: TranscriptionBridgeIntent) => void;
        };
        audioFileUploadBridge?: {
          postMessage: (message: AudioFileUploadBridgeIntent) => void;
        };
      };
    };
    basilTranscriptionWidget?: {
      onEvent: (event: TranscriptionBridgeEvent) => void;
    };
    basilAudioFileUpload?: {
      onEvent: (event: AudioFileUploadBridgeEvent) => void;
    };
  }
}

export {};
