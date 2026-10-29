import type { FontPayload, ThemePayload } from '../types'
import { applySurfaceFinish } from '@shared/surfaceFinish'
import { markHostThemeApplied } from '@shared/hostThemeSignal'
import { applyTextOnColorTokens, normalizeTextScale } from '@shared/webTheme'

/**
 * Applies native-supplied theme colors and fonts as CSS custom properties on
 * the document root. Called from every consumer that receives an `init` or
 * `themeChanged` event over the `basilAppearanceSettingsBridge` channel, not
 * just the Appearance & Format tab itself -- the rest of the Settings shell
 * renders with these same variables and must not wait for the user to visit
 * Appearance & Format before picking up the real color/font preferences.
 */
export function applyHostTheme(theme: ThemePayload, fonts: FontPayload) {
  const root = document.documentElement
  root.style.setProperty('--background-primary', theme.backgroundPrimary)
  root.style.setProperty('--background-secondary', theme.backgroundSecondary)
  root.style.setProperty('--background-tertiary', theme.backgroundTertiary)
  root.style.setProperty('--primary', theme.primary)
  root.style.setProperty('--secondary', theme.secondary)
  // textPrimary/separatorColor/fieldBorder are published under --host-* names
  // instead of their canonical --text-primary/--separator-color/--field-border
  // names. appearance-settings.css's palette-aware "wireframe-feel" :root rule
  // derives the real --text-primary/--separator-color/--field-border from
  // these --host-* inputs via color-mix(); a stylesheet rule cannot reference
  // the very custom property this function also sets inline (that would be a
  // circular reference), so the raw palette value has to land under a
  // different name for the derivation to read it.
  root.style.setProperty('--host-text-primary', theme.textPrimary)
  root.style.setProperty('--text-secondary', theme.textSecondary)
  root.style.setProperty('--text-tertiary', theme.textTertiary)
  root.style.setProperty('--host-separator-color', theme.separatorColor)
  root.style.setProperty('--host-field-border', theme.fieldBorder)
  root.style.setProperty('--recording-base', theme.recordingBase)
  root.style.setProperty('--recording-accent', theme.recordingAccent)
  root.style.setProperty('--processing-base', theme.processingBase)
  root.style.setProperty('--processing-accent', theme.processingAccent)
  root.style.setProperty('--warning-base', theme.warningBase)
  applyTextOnColorTokens(theme)
  applySurfaceFinish(theme.surfaceFinish)
  // Settings follows the app-wide text size like every other window, so a size picked here is visible in this window as it is previewed.
  const textScale = normalizeTextScale(theme.textScale)
  if (textScale !== undefined) root.style.setProperty('--text-scale', String(textScale))
  root.style.setProperty('--font-family', fonts.fontFamily)
  root.style.setProperty('--font-family-light', fonts.fontFamily)
  root.style.setProperty('--font-family-medium', fonts.fontFamilyMedium)
  root.style.setProperty('--font-family-bold', fonts.fontFamilyBold)
  // The blueprint reveal waits for this: it measures what paints, so it needs the real colors and fonts.
  markHostThemeApplied()
}
