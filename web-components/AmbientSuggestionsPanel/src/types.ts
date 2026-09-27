import type { ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  processingRgb?: string;
  secondary: string;
  textPrimary: string;
};

export interface FontConfig {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
}

export interface InitMessage {
  port: number;
  theme: ThemeConfig;
  fonts: FontConfig;
}

export interface EvaluationModel {
  id: string;
  displayName: string;
  isLocal: boolean;
}

export interface AnchorRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AmbientRuntimeStatus {
  initialized: boolean;
  enabled: boolean;
  is_running?: boolean;
  frequency_minutes?: number;
  frequency_seconds?: number;
  evaluation_model?: string;
  mode?: string;
  open_suggestions_count?: number;
  is_evaluating?: boolean;
  evaluation_started_at?: string | null;
  last_evaluation_completed_at?: string | null;
  next_evaluation_time?: string | null;
  last_status_message?: string | null;
}

export interface AmbientSuggestionSettings {
  enabled: boolean;
  frequency_seconds?: number;
  evaluation_model?: string;
}

export interface AmbientStatusChangedMessage {
  status: AmbientRuntimeStatus;
  reason?: string;
}

export interface AmbientSuggestion {
  suggestion_id: string;
  app_name: string;
  window_title: string;
  capability: 'assistant_session' | 'agent_task';
  suggestion_type: string;
  title: string;
  summary: string;
  details?: string | null;
  proposed_request?: string | null;
  instruction?: string | null;
  confidence: number;
}

export type SwiftMessage =
  | { type: 'ambientPanelReady' }
  | { type: 'acceptSuggestion'; suggestionId: string }
  | { type: 'rejectSuggestion'; suggestionId: string }
  | { type: 'dismissPanel' }
  | { type: 'minimizePanel' }
  | { type: 'toggleCollapsePanel'; compactSize?: { width: number; height: number } }
  | { type: 'ambientRuntimeChanged' }
  | { type: 'showModelPicker'; models: EvaluationModel[]; selectedModelId: string; anchorRect: AnchorRect }
  | { type: 'requestResize'; width: number; height: number };
