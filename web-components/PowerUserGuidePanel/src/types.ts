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

export type HotkeyId = 'transcription' | 'assistantSession' | 'agentTask' | 'conversation'

/** One saved hotkey as the app reports it. `display` is the app's keycap text, such as "⌥␣" or "⌘⌘". */
export interface HotkeyInfo {
  display: string
  enabled: boolean
  isDoublePress: boolean
  doublePressKey?: string
}

export type HotkeyMap = Partial<Record<HotkeyId, HotkeyInfo>>

export interface InitMessage {
  theme: ThemeConfig
  fonts: FontConfig
  hotkeys?: HotkeyMap
}

export type SectionId =
  | 'transcription'
  | 'assistantSession'
  | 'agentTasks'
  | 'dillOrPaprika'
  | 'conversation'
  | 'activityCapture'
  | 'models'
  | 'windowShortcuts'

export type SwiftMessage =
  | { type: 'rendererReady' }
  | { type: 'dismiss' }
