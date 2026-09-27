// web-components/AssistantSession/src/bridge/types.ts
//
// Wire contract for window.webkit.messageHandlers.assistantSessionBridge. Mirrors MeetingAssistant's snapshot/delta/protocolVersion-gated shape (see assistantSessionReducer.ts for staleness rejection).

export const PROTOCOL_VERSION = 1;

export type AssistantSessionStatus = 'idle' | 'running' | 'completed' | 'failed';
export type AssistantSessionInputMode = 'speak' | 'type';
export type AssistantSessionBubbleMode = 'audioResponsive' | 'processing' | 'ambient';

export interface AssistantSessionModelInfo {
  id: string;
  displayName: string;
  isApiModel: boolean;
}

export interface AssistantSessionModelPickerAnchorRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Fixed (non-user-configurable) design tokens, mirrored 1:1 from AestheticSystem.Layout / .Typography. */
export const AssistantSessionLayout = {
  cornerRadiusSmall: 6,
  cornerRadiusMedium: 8,
  cornerRadiusLarge: 16,
  paddingXS: 4,
  paddingS: 8,
  paddingM: 12,
  paddingL: 16,
  paddingXL: 20,
  borderThin: 1,
  borderMedium: 2,
} as const;

/** User-configurable colors are delivered at runtime through AssistantSessionThemePayload, mirroring AgentTaskResult's established theme-change bridge because AestheticSystem settings are dynamic per user. */
import type { ThemeConfig } from '@shared/webTheme';

export type AssistantSessionThemePayload = ThemeConfig & {
  primary: string;
  secondary: string;
  backgroundPrimary: string;
  backgroundSecondary: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  recordingBase: string;
  recordingAccent: string;
  readyBase: string;
  readyAccent: string;
  processingBase: string;
  processingAccent: string;
  successBase: string;
  errorBase: string;
  preferredFontName: string;
};

export interface AssistantSessionSnapshotPayload {
  ocrStatus: AssistantSessionStatus;
  transcriptionStatus: AssistantSessionStatus;
  assistantSessionStatus: AssistantSessionStatus;
  errorMessage: string | null;
  assistantOutput: string;
  fallbackModelUsed: string | null;
  thinkingContent: string | null;
  isRecording: boolean;
  audioLevel: number;
  elapsedSeconds: number;
  transcriptionText: string;
  transcriptionProgressMessage: string | null;
  transcriptionProgressFraction: number | null;
  shouldPersistUI: boolean;
  isResultChromeCollapsed: boolean;
  hasTextSelection: boolean;
  selectedText: string | null;
  detectedApplicationName: string | null;
  isRefinementMode: boolean;
  iterationCount: number;
  showRefinementIndicator: boolean;
  inputMode: AssistantSessionInputMode;
  inputCommitted: boolean;
  typedInstruction: string;
  ocrText: string | null;
  canSubmitTypedInstruction: boolean;
  selectedModelId: string | null;
  availableModels: AssistantSessionModelInfo[];
  localModels: AssistantSessionModelInfo[];
  apiModels: AssistantSessionModelInfo[];
  useApiModels: boolean;
  isLoadingModels: boolean;
  sampleSaved: boolean;
  savingSample: boolean;
  isEditMode: boolean;
  editableContentSeed: string;
  hotkeyDisplayString: string | null;
  bubbleMode: AssistantSessionBubbleMode;
  bubbleColors: { base: string; accent: string };
}

export interface AssistantSessionInitPayload {
  theme: AssistantSessionThemePayload;
}

export type AssistantSessionBridgeEvent =
  | ({ type: 'init'; protocolVersion: number } & AssistantSessionInitPayload)
  | ({ type: 'themeChanged' } & AssistantSessionThemePayload)
  | ({ type: 'snapshot'; revision: number; protocolVersion: number } & AssistantSessionSnapshotPayload)
  | ({ type: 'delta'; revision: number; protocolVersion: number } & Partial<AssistantSessionSnapshotPayload>)
  | { type: 'meter'; audioLevel: number };

export type AssistantSessionBridgeIntent =
  | { type: 'reactReady'; protocolVersion: number }
  | { type: 'cancelOperation' }
  | { type: 'minimizeWidget' }
  | { type: 'toggleResultCollapse' }
  | { type: 'switchInputMode'; mode: AssistantSessionInputMode }
  | { type: 'submitTypedInstruction'; text: string }
  | { type: 'stopRecording' }
  | { type: 'selectModel'; modelId: string }
  | { type: 'showNativeModelPicker'; models: AssistantSessionModelInfo[]; selectedModelId: string | null; anchorRect: AssistantSessionModelPickerAnchorRect }
  | { type: 'enterEditMode' }
  | { type: 'cancelEditMode' }
  | { type: 'applyEdits'; content: string }
  | { type: 'saveAsSample'; content: string | null }
  | { type: 'enterVoiceRefinement' }
  | { type: 'enterTypedRefinement' }
  | { type: 'cancelTypedRefinement' }
  | { type: 'submitTypedRefinement'; text: string }
  | { type: 'stopRefinementRecording' }
  | { type: 'copyRichText' }
  | { type: 'copyMarkdown' }
  | { type: 'openExternalUrl'; url: string }
  | { type: 'openHistory' }
  | { type: 'requestResize'; width: number; height: number };
