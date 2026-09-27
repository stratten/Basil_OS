// web-components/AssistantSession/src/state/assistantSessionReducer.ts

import { PROTOCOL_VERSION } from '../bridge/types';
import type {
  AssistantSessionBridgeEvent,
  AssistantSessionSnapshotPayload,
  AssistantSessionThemePayload,
} from '../bridge/types';

export interface AssistantSessionState extends AssistantSessionSnapshotPayload {
  revision: number;
  hasSnapshot: boolean;
  theme: AssistantSessionThemePayload | null;
}

const DEFAULT_THEME_FALLBACK: AssistantSessionThemePayload = {
  // Design-time fallback for isolated rendering only; authoritative values arrive through the init/themeChanged bridge before the real widget is shown.
  primary: '#2F6FED',
  secondary: '#4C7BF0',
  backgroundPrimary: '#FFFFFF',
  backgroundSecondary: '#F5F6F8',
  textPrimary: '#111318',
  textSecondary: '#5B6270',
  textTertiary: '#9AA1AC',
  recordingBase: '#8B0000',
  recordingAccent: '#C23B3B',
  readyBase: '#2F6FED',
  readyAccent: '#8FB2F7',
  processingBase: '#7C3AED',
  processingAccent: '#DDD6FE',
  successBase: '#1E8E5A',
  errorBase: '#D33B3B',
  preferredFontName: '-apple-system',
};

export const initialAssistantSessionState: AssistantSessionState = {
  revision: 0,
  hasSnapshot: false,
  theme: null,
  ocrStatus: 'idle',
  transcriptionStatus: 'idle',
  assistantSessionStatus: 'idle',
  errorMessage: null,
  assistantOutput: '',
  fallbackModelUsed: null,
  thinkingContent: null,
  isRecording: false,
  audioLevel: 0,
  elapsedSeconds: 0,
  transcriptionText: '',
  transcriptionProgressMessage: null,
  transcriptionProgressFraction: null,
  shouldPersistUI: false,
  isResultChromeCollapsed: false,
  hasTextSelection: false,
  selectedText: null,
  detectedApplicationName: null,
  isRefinementMode: false,
  iterationCount: 0,
  showRefinementIndicator: false,
  inputMode: 'speak',
  inputCommitted: false,
  typedInstruction: '',
  ocrText: null,
  canSubmitTypedInstruction: false,
  selectedModelId: null,
  availableModels: [],
  localModels: [],
  apiModels: [],
  useApiModels: false,
  isLoadingModels: false,
  sampleSaved: false,
  savingSample: false,
  isEditMode: false,
  editableContentSeed: '',
  hotkeyDisplayString: null,
  bubbleMode: 'ambient',
  bubbleColors: { base: DEFAULT_THEME_FALLBACK.readyBase, accent: DEFAULT_THEME_FALLBACK.readyAccent },
};

export function resolveTheme(state: AssistantSessionState): AssistantSessionThemePayload {
  return state.theme ?? DEFAULT_THEME_FALLBACK;
}

export function applyAssistantSessionEvent(
  state: AssistantSessionState,
  event: AssistantSessionBridgeEvent,
): AssistantSessionState {
  if (event.type === 'meter') {
    // Meter events never touch revisioned state; the bubble subscribes to them separately.
    return state;
  }

  if (event.type === 'init') {
    if (event.protocolVersion !== PROTOCOL_VERSION) {
      // eslint-disable-next-line no-console
      console.error(
        `[assistantSessionReducer] rejecting init with unsupported protocolVersion=${event.protocolVersion}, expected ${PROTOCOL_VERSION}`,
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
      `[assistantSessionReducer] rejecting event with unsupported protocolVersion=${event.protocolVersion}, expected ${PROTOCOL_VERSION}`,
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
      `[assistantSessionReducer] dropping stale delta revision=${event.revision}, current=${state.revision}`,
    );
    return state;
  }

  const { type, revision, protocolVersion, ...payload } = event;
  return { ...state, ...payload, revision };
}
