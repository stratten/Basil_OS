// web-components/TranscriptionWidget/src/bridge/audioFileUploadTypes.ts
//
// Wire contract for window.webkit.messageHandlers.audioFileUploadBridge.
// Separate channel/window from transcriptionWidgetBridge -- same
// "one channel per window" precedent as AssistantOutputHistory's
// assistantOutputHistoryBridge alongside assistantSessionBridge.

export const AUDIO_UPLOAD_PROTOCOL_VERSION = 1;
import type { FontConfig, ThemeConfig } from '@shared/webTheme';

export interface AudioUploadLanguageOption {
  label: string;
  value: string;
}

export const AUDIO_UPLOAD_LANGUAGE_OPTIONS: AudioUploadLanguageOption[] = [
  { label: 'Auto-detect', value: 'auto' },
  { label: 'English', value: 'en' },
  { label: 'Spanish', value: 'es' },
  { label: 'French', value: 'fr' },
  { label: 'German', value: 'de' },
  { label: 'Italian', value: 'it' },
  { label: 'Portuguese', value: 'pt' },
  { label: 'Japanese', value: 'ja' },
  { label: 'Chinese', value: 'zh' },
  { label: 'Korean', value: 'ko' },
  { label: 'Russian', value: 'ru' },
];

export type AudioFileUploadThemePayload = ThemeConfig & {
  primary: string;
  secondary: string;
  backgroundPrimary: string;
  textPrimary: string;
  textSecondary: string;
  errorBase: string;
  fonts?: FontConfig;
};

export interface AudioFileUploadSnapshotPayload {
  hasSelectedFile: boolean;
  selectedFileName: string | null;
  fileSizeDisplay: string | null;
  fileDurationDisplay: string | null;
  description: string;
  selectedLanguage: string;
  isUploading: boolean;
  uploadStatus: string;
  transcriptionResult: string | null;
  canUpload: boolean;
  errorMessage: string | null;
}

export type AudioFileUploadBridgeEvent =
  | ({ type: 'init'; protocolVersion: number } & { theme: AudioFileUploadThemePayload })
  | ({ type: 'themeChanged' } & AudioFileUploadThemePayload)
  | ({ type: 'snapshot'; revision: number; protocolVersion: number } & AudioFileUploadSnapshotPayload)
  | ({ type: 'delta'; revision: number; protocolVersion: number } & Partial<AudioFileUploadSnapshotPayload>);

export type AudioFileUploadBridgeIntent =
  | { type: 'reactReady'; protocolVersion: number }
  | { type: 'selectAudioFile' }
  | { type: 'clearSelectedFile' }
  | { type: 'setDescription'; value: string }
  | { type: 'setLanguage'; value: string }
  | { type: 'upload' }
  | { type: 'copyTranscriptionResult' }
  | { type: 'dismissError' }
  | { type: 'cancel' }
  | { type: 'minimize' }
  | { type: 'collapse' }
  | { type: 'expand' };
