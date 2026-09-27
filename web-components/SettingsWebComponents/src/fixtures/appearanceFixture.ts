import type { AppearanceSettings } from '../types'

export const APPEARANCE_FIXTURE_SETTINGS: Readonly<AppearanceSettings> = Object.freeze({
  backgroundColorRed: 1.0,
  backgroundColorGreen: 1.0,
  backgroundColorBlue: 1.0,
  primaryColorRed: 0.0,
  primaryColorGreen: 0.188,
  primaryColorBlue: 0.529,
  secondaryColorRed: 0.2,
  secondaryColorGreen: 0.333,
  secondaryColorBlue: 0.608,
  textColorRed: 0.0,
  textColorGreen: 0.0,
  textColorBlue: 0.0,
  processingColorRed: 0.486,
  processingColorGreen: 0.227,
  processingColorBlue: 0.929,
  processingAccentColorRed: 0.867,
  processingAccentColorGreen: 0.839,
  processingAccentColorBlue: 0.996,
  preferredFont: 'Helvetica-Light',
})

export const APPEARANCE_FIXTURE_AVAILABLE_FONTS: readonly string[] = Object.freeze([
  'Helvetica-Light',
  'Arial',
  'Avenir-Light',
  'SF Pro Text',
  'Menlo',
])

export const APPEARANCE_FIXTURE_REVISION = 1
