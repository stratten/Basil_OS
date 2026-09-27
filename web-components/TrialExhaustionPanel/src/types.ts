import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

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
  remainingBalanceFormatted: string
  limitFormatted: string
  isAuthenticated: boolean
  userEmail: string | null
}

export type UseLocalModelsResultStatus = 'success' | 'failure'

export interface UseLocalModelsResult {
  requestId: string
  status: UseLocalModelsResultStatus
  message?: string
}

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'requestResize'; width: number; height: number }
  | { type: 'dismiss' }
  | { type: 'signUp' }
  | { type: 'addOwnKeys' }
  | { type: 'useLocalModels'; requestId: string }
