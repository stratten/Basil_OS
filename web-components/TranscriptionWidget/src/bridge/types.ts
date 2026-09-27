// web-components/TranscriptionWidget/src/bridge/types.ts
//
// Wire contract for window.webkit.messageHandlers.transcriptionWidgetBridge.
// Mirrors AssistantSession's snapshot/delta/protocolVersion-gated shape
// (see AssistantSession/src/bridge/types.ts) but trimmed to the fields
// TranscriptionWidgetViewModel actually publishes.

export const PROTOCOL_VERSION = 1;
import type { ThemeConfig } from '@shared/webTheme';

export interface TranscriptionModelInfo {
  id: string;
  displayName: string;
  isApiModel: boolean;
}

export const TranscriptionLayout = {
  cornerRadiusSmall: 6,
  cornerRadiusLarge: 16,
  cornerRadiusMinimized: 12,
  paddingXS: 4,
  paddingS: 8,
  paddingM: 12,
} as const;

export type TranscriptionThemePayload = ThemeConfig & {
  primary: string;
  secondary: string;
  backgroundPrimary: string;
  textPrimary: string;
  textSecondary: string;
  recordingBase: string;
  errorBase: string;
  warningBase: string;
  preferredFontName: string;
};

export interface TranscriptionSnapshotPayload {
  isRecording: boolean;
  isStartingRecording: boolean;
  isProcessingRecording: boolean;
  isConnected: boolean;
  isModelReady: boolean;
  isModelLoading: boolean;
  error: string | null;
  transcriptionText: string;
  audioLevel: number;
  elapsedSeconds: number;
  isMinimized: boolean;
  canToggleRecording: boolean;
  currentTranscriptionModelId: string;
  availableTranscriptionModels: TranscriptionModelInfo[];
  isSwappingTranscriptionModel: boolean;
  hotkeyDisplayString: string | null;
  bubbleMode: 'audioResponsive' | 'processing' | 'ambient';
  bubbleColors: { base: string; accent: string };
}

export interface TranscriptionInitPayload {
  theme: TranscriptionThemePayload;
}

export type TranscriptionBridgeEvent =
  | ({ type: 'init'; protocolVersion: number } & TranscriptionInitPayload)
  | ({ type: 'themeChanged' } & TranscriptionThemePayload)
  | ({ type: 'snapshot'; revision: number; protocolVersion: number } & TranscriptionSnapshotPayload)
  | ({ type: 'delta'; revision: number; protocolVersion: number } & Partial<TranscriptionSnapshotPayload>)
  | { type: 'meter'; audioLevel: number };

export type TranscriptionBridgeIntent =
  | { type: 'reactReady'; protocolVersion: number }
  | { type: 'toggleRecording' }
  | { type: 'cancelRecording' }
  | { type: 'toggleMinimizedState' }
  | { type: 'close' }
  | { type: 'clearTranscription' }
  | { type: 'copyToClipboard' }
  | { type: 'selectTranscriptionModel'; modelId: string }
  | { type: 'showTranscriptionModelMenu'; models: TranscriptionModelInfo[]; selectedModelId: string; anchorRect: { x: number; y: number; width: number; height: number } }
  | { type: 'openSystemMicrophoneSettings' }
  | { type: 'showErrorPopover' }
  | { type: 'requestResize'; width: number; height: number };
