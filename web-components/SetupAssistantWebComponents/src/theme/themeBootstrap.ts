import { useEffect } from 'react'

import { applyHostFonts, applyHostTheme } from '@shared/webTheme'
import type { FontConfig, ThemeConfig } from '@shared/webTheme'

export type { FontConfig, ThemeConfig }
export { applyHostFonts, applyHostTheme }

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
