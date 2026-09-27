import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string
  primary: string
  secondary: string
  textPrimary: string
}

export type FontConfig = SharedFontConfig & {
  fontFamily: string
  fontFamilyMedium: string
  fontFamilyBold: string
}

export interface ModelRowSnapshot {
  modelId: string
  status: string
  progress: number
  totalDownloaded: number | null
  totalSize: number | null
  isRetrying: boolean
}

export interface PanelSnapshot {
  phaseMessage: string
  isComplete: boolean
  quantizedPercentage: number
  appIconDataUrl?: string | null
  models: ModelRowSnapshot[]
}

export interface InitMessage {
  theme: ThemeConfig
  fonts: FontConfig
  snapshot: PanelSnapshot
}

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'dismiss' }
  | { type: 'retryModel'; modelId: string }
  | { type: 'cancelModel'; modelId: string }
  | { type: 'requestResize'; width: number; height: number }
