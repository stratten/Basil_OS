import type { TranscriptionBridgeEvent } from './types';
import type { AudioFileUploadBridgeEvent } from './audioFileUploadTypes';

declare global {
  interface Window {
    basilTranscriptionWidget?: {
      onEvent: (event: TranscriptionBridgeEvent) => void;
    };
    basilAudioFileUpload?: {
      onEvent: (event: AudioFileUploadBridgeEvent) => void;
    };
  }
}

export {};
