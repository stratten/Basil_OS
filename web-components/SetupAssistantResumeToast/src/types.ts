import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme'

export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string
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

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'requestResize'; width: number; height: number }
  | { type: 'resume' }
  | { type: 'remindLater' }
  | { type: 'dontRemind' }
