// web-components/TranscriptionWidget/src/state/audioFileUploadReducer.ts

import { AUDIO_UPLOAD_PROTOCOL_VERSION } from '../bridge/audioFileUploadTypes';
import type {
  AudioFileUploadBridgeEvent,
  AudioFileUploadSnapshotPayload,
  AudioFileUploadThemePayload,
} from '../bridge/audioFileUploadTypes';

export interface AudioFileUploadState extends AudioFileUploadSnapshotPayload {
  revision: number;
  hasSnapshot: boolean;
  theme: AudioFileUploadThemePayload | null;
}

const DEFAULT_THEME_FALLBACK: AudioFileUploadThemePayload = {
  primary: '#2F6FED',
  secondary: '#4C7BF0',
  backgroundPrimary: '#FFFFFF',
  textPrimary: '#111318',
  textSecondary: '#5B6270',
  errorBase: '#D33B3B',
};

export const initialAudioFileUploadState: AudioFileUploadState = {
  revision: 0,
  hasSnapshot: false,
  theme: null,
  hasSelectedFile: false,
  selectedFileName: null,
  fileSizeDisplay: null,
  fileDurationDisplay: null,
  description: '',
  selectedLanguage: 'auto',
  isUploading: false,
  uploadStatus: 'Preparing upload...',
  transcriptionResult: null,
  canUpload: false,
  errorMessage: null,
};

export function resolveAudioUploadTheme(state: AudioFileUploadState): AudioFileUploadThemePayload {
  return state.theme ?? DEFAULT_THEME_FALLBACK;
}

export function applyAudioFileUploadEvent(
  state: AudioFileUploadState,
  event: AudioFileUploadBridgeEvent,
): AudioFileUploadState {
  if (event.type === 'init') {
    if (event.protocolVersion !== AUDIO_UPLOAD_PROTOCOL_VERSION) {
      // eslint-disable-next-line no-console
      console.error(`[audioFileUploadReducer] rejecting init with unsupported protocolVersion=${event.protocolVersion}`);
      return state;
    }
    return { ...state, theme: event.theme };
  }

  if (event.type === 'themeChanged') {
    const { type, ...theme } = event;
    return { ...state, theme };
  }

  if (event.protocolVersion !== AUDIO_UPLOAD_PROTOCOL_VERSION) {
    // eslint-disable-next-line no-console
    console.error(`[audioFileUploadReducer] rejecting event with unsupported protocolVersion=${event.protocolVersion}`);
    return state;
  }

  if (event.type === 'snapshot') {
    const { type, revision, protocolVersion, ...payload } = event;
    return { ...state, ...payload, revision, hasSnapshot: true };
  }

  if (event.revision <= state.revision) {
    // eslint-disable-next-line no-console
    console.warn(`[audioFileUploadReducer] dropping stale delta revision=${event.revision}, current=${state.revision}`);
    return state;
  }

  const { type, revision, protocolVersion, ...payload } = event;
  return { ...state, ...payload, revision };
}
