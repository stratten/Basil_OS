import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme'

export type ThemeConfig = SharedThemeConfig
export type FontConfig = SharedFontConfig

export interface InitMessage {
  theme: ThemeConfig
  fonts: FontConfig
  message: string
}

export type StatusMessage = {
  message: string
}

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'drawnIn' }
  | { type: 'close' }
  | { type: 'minimize' }
  | { type: 'collapse' }
  | { type: 'expand' }
