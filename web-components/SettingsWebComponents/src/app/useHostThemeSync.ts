import { useEffect } from 'react'
import { notifyAppearanceSettingsReady, onAppearanceEvent } from '../services/bridge'
import { applyHostTheme } from '../services/hostTheme'

/**
 * Keeps `--background-primary`, `--primary`, `--font-family-*`, and the rest
 * of the host-theme CSS custom properties in sync with the user's real
 * Appearance & Format preferences from the moment the Settings window opens,
 * regardless of which tab is selected. Without this, every tab other than
 * Appearance & Format would render with the static fallback values baked
 * into theme.css until the user happened to visit that one tab, because
 * `applyHostTheme` previously only ran from inside `AppearanceSettingsApp`'s
 * own mount effect. Call this once, unconditionally, from `SettingsShell`.
 */
export function useHostThemeSync() {
  useEffect(() => {
    const unsubscribe = onAppearanceEvent((event) => {
      if (event.type === 'init' || event.type === 'themeChanged') {
        applyHostTheme(event.theme, event.fonts)
      }
    })
    notifyAppearanceSettingsReady()
    return unsubscribe
  }, [])
}
