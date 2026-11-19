import { useEffect } from 'react'

import { applyHostFonts, applyHostTheme } from '@shared/theme/webTheme'
import type { FontConfig, ThemeConfig } from '@shared/theme/webTheme'

export type { FontConfig, ThemeConfig }
export { applyHostFonts, applyHostTheme }

export interface SetupAssistantHostConfig {
  apiBaseUrl?: string
  theme?: ThemeConfig
  fonts?: FontConfig
  isReturningUserCheck?: boolean
  // Basil's default hotkeys that share keys with a macOS shortcut that is on. Read once when the window opens.
  systemShortcutConflicts?: SetupSystemShortcutConflict[]
}

export interface SetupSystemShortcutConflict {
  hotkeyId: string
  source: string
  certainty: 'exact' | 'possible'
  message: string
}

declare global {
  interface Window {
    basilSetupAssistantConfig?: SetupAssistantHostConfig
  }
}

interface SetupAssistantThemeChangedDetail {
  theme?: ThemeConfig
  fonts?: FontConfig
}

export function useSetupAssistantTheme(): void {
  useEffect(() => {
    applyHostTheme(window.basilSetupAssistantConfig?.theme)
    applyHostFonts(window.basilSetupAssistantConfig?.fonts)

    function handleThemeChanged(event: Event) {
      const detail = (event as CustomEvent<SetupAssistantThemeChangedDetail>).detail
      applyHostTheme(detail?.theme)
      applyHostFonts(detail?.fonts)
    }

    window.addEventListener('setupAssistantThemeChanged', handleThemeChanged)
    return () => {
      window.removeEventListener('setupAssistantThemeChanged', handleThemeChanged)
    }
  }, [])
}
