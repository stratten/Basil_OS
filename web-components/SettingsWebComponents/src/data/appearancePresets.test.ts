import { describe, expect, it } from 'vitest'
import { customThemeNameError, customThemePreset } from './appearancePresets'
import type { CustomAppearanceTheme } from '../types'

const harbor: CustomAppearanceTheme = {
  id: 'custom-0123456789abcdef0123456789abcdef',
  name: 'Harbor',
  backgroundColorRed: 0.1,
  backgroundColorGreen: 0.2,
  backgroundColorBlue: 0.3,
  primaryColorRed: 0.4,
  primaryColorGreen: 0.5,
  primaryColorBlue: 0.6,
  secondaryColorRed: 0.7,
  secondaryColorGreen: 0.8,
  secondaryColorBlue: 0.9,
  textColorRed: 1,
  textColorGreen: 0.95,
  textColorBlue: 0.9,
  surfaceFinish: 'metal',
}

describe('customThemePreset', () => {
  it('maps flat theme fields onto the preset color shape', () => {
    expect(customThemePreset(harbor)).toEqual({
      id: harbor.id,
      name: 'Harbor',
      background: { red: 0.1, green: 0.2, blue: 0.3 },
      primary: { red: 0.4, green: 0.5, blue: 0.6 },
      secondary: { red: 0.7, green: 0.8, blue: 0.9 },
      text: { red: 1, green: 0.95, blue: 0.9 },
    })
  })
})

describe('customThemeNameError', () => {
  it('accepts a new trimmed name', () => {
    expect(customThemeNameError('  Lagoon  ', [harbor])).toBeNull()
  })

  it('rejects a blank name', () => {
    expect(customThemeNameError('   ', [])).toBe('Enter a theme name.')
  })

  it('enforces the 40-character limit in code points', () => {
    expect(customThemeNameError('x'.repeat(40), [])).toBeNull()
    expect(customThemeNameError('x'.repeat(41), [])).toBe('Theme names can be up to 40 characters.')
    expect(customThemeNameError('🎨'.repeat(40), [])).toBeNull()
  })

  it('rejects built-in and custom names case-insensitively', () => {
    expect(customThemeNameError('precursor', [])).toBe('A theme with that name already exists.')
    expect(customThemeNameError(' HARBOR ', [harbor])).toBe('A theme with that name already exists.')
  })
})
