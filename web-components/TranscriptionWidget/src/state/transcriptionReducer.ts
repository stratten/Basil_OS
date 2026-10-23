// web-components/TranscriptionWidget/src/state/transcriptionReducer.ts

import { PROTOCOL_VERSION } from '../bridge/types';
import type {
  TranscriptionBridgeEvent,
  TranscriptionSnapshotPayload,
  TranscriptionThemePayload,
} from '../bridge/types';

export interface TranscriptionState extends TranscriptionSnapshotPayload {
  revision: number;
  hasSnapshot: boolean;
  theme: TranscriptionThemePayload | null;
}

const DEFAULT_THEME_FALLBACK: TranscriptionThemePayload = {
  // Design-time fallback for isolated rendering only; authoritative values arrive through the init/themeChanged bridge before the real widget is shown.
  primary: '#2F6FED',
  secondary: '#4C7BF0',
  backgroundPrimary: '#FFFFFF',
  textPrimary: '#111318',
  textSecondary: '#5B6270',
  recordingBase: '#8B0000',
  errorBase: '#D33B3B',
  warningBase: '#B8860B',
  preferredFontName: '-apple-system',
};

export const initialTranscriptionState: TranscriptionState = {
  revision: 0,
  hasSnapshot: false,
  theme: null,
  isRecording: false,
  isStartingRecording: false,
  isProcessingRecording: false,
  isConnected: false,
  isModelReady: false,
  isModelLoading: false,
  error: null,
  transcriptionText: 'Initializing transcription service...',
  audioLevel: 0,
  elapsedSeconds: 0,
  isMinimized: false,
  canToggleRecording: false,
  currentTranscriptionModelId: '',
  availableTranscriptionModels: [],
  isSwappingTranscriptionModel: false,
  hotkeyDisplayString: null,
  bubbleMode: 'ambient',
  bubbleColors: { base: DEFAULT_THEME_FALLBACK.recordingBase, accent: DEFAULT_THEME_FALLBACK.recordingBase },
};

export function resolveTheme(state: TranscriptionState): TranscriptionThemePayload {
  return state.theme ?? DEFAULT_THEME_FALLBACK;
}

export function applyTranscriptionEvent(
  state: TranscriptionState,
  event: TranscriptionBridgeEvent,
): TranscriptionState {
  if (event.type === 'meter') {
    // Meter events never touch revisioned state; the bubble subscribes to them separately.
    return state;
  }

  if (event.type === 'init') {
    if (event.protocolVersion !== PROTOCOL_VERSION) {
      // eslint-disable-next-line no-console
      console.error(
        `[transcriptionReducer] rejecting init with unsupported protocolVersion=${event.protocolVersion}, expected ${PROTOCOL_VERSION}`,
      );
      return state;
    }
    return { ...state, theme: event.theme };
  }

  if (event.type === 'themeChanged') {
    const { type, ...theme } = event;
    return { ...state, theme };
  }

  if (event.protocolVersion !== PROTOCOL_VERSION) {
    // eslint-disable-next-line no-console
    console.error(
      `[transcriptionReducer] rejecting event with unsupported protocolVersion=${event.protocolVersion}, expected ${PROTOCOL_VERSION}`,
    );
    return state;
  }

  if (event.type === 'snapshot') {
    const { type, revision, protocolVersion, ...payload } = event;
    return { ...state, ...payload, revision, hasSnapshot: true };
  }

  // event.type === 'delta'
  if (event.revision <= state.revision) {
    // eslint-disable-next-line no-console
    console.warn(
      `[transcriptionReducer] dropping stale delta revision=${event.revision}, current=${state.revision}`,
    );
    return state;
  }

  const { type, revision, protocolVersion, ...payload } = event;
  return { ...state, ...payload, revision };
}
