import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string
  backgroundSecondary: string
  primary: string
  textPrimary: string
  textSecondary: string
}

export type FontConfig = SharedFontConfig & {
  fontFamily: string
  fontFamilyMedium: string
  fontFamilyBold: string
}

export interface InitMessage {
  theme: ThemeConfig
  fonts: FontConfig
}

export type SectionId =
  | 'transcription'
  | 'assistantSession'
  | 'agentTasks'
  | 'voiceComparison'
  | 'conversation'
  | 'activityCapture'
  | 'models'

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'dismiss' }
