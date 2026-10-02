import type { CustomAppearanceTheme } from '../types'

export interface AppearancePresetColor {
  red: number
  green: number
  blue: number
}

export interface AppearancePreset {
  id: string
  name: string
  background: AppearancePresetColor
  primary: AppearancePresetColor
  secondary: AppearancePresetColor
  text: AppearancePresetColor
}

export const APPEARANCE_PRESETS: AppearancePreset[] = [
  {
    id: 'duke-blue',
    name: 'Duke Blue',
    background: { red: 0.0709251779736389, green: 0.10432000903519285, blue: 0.22791699626277573 },
    primary: { red: 0.21100852777444695, green: 0.4699344845863317, blue: 0.8893695758678611 },
    secondary: { red: 0.376, green: 0.647, blue: 0.98 },
    text: { red: 0.9699399998499855, green: 0.9902393003857255, blue: 1.0 },
  },
  {
    id: 'athens',
    name: 'Athens',
    background: { red: 1, green: 1, blue: 1 },
    primary: { red: 0.0, green: 0.188, blue: 0.529 },
    secondary: { red: 0.2, green: 0.333, blue: 0.608 },
    text: { red: 0, green: 0, blue: 0 },
  },
  {
    id: 'midnight',
    name: 'Midnight',
    background: { red: 0.078, green: 0.086, blue: 0.106 },
    primary: { red: 0.231, green: 0.510, blue: 0.965 },
    secondary: { red: 0.376, green: 0.647, blue: 0.980 },
    text: { red: 0.961, green: 0.965, blue: 0.973 },
  },
  {
    id: 'slate-copper',
    name: 'Slate & Copper',
    background: { red: 0.980, green: 0.976, blue: 0.965 },
    primary: { red: 0.200, green: 0.255, blue: 0.333 },
    secondary: { red: 0.706, green: 0.325, blue: 0.035 },
    text: { red: 0.067, green: 0.094, blue: 0.153 },
  },
  {
    id: 'basil-forest',
    name: 'Basil Forest',
    background: { red: 0.965, green: 0.953, blue: 0.918 },
    primary: { red: 0.118, green: 0.275, blue: 0.125 },
    secondary: { red: 0.549, green: 0.239, blue: 0.169 },
    text: { red: 0.106, green: 0.106, blue: 0.094 },
  },
  {
    id: 'monochrome-ink',
    name: 'Monochrome Ink',
    background: { red: 1, green: 1, blue: 1 },
    primary: { red: 0.067, green: 0.067, blue: 0.067 },
    secondary: { red: 0.294, green: 0.294, blue: 0.294 },
    text: { red: 0, green: 0, blue: 0 },
  },
  {
    id: 'plum-rose',
    name: 'Plum & Rose',
    background: { red: 0.984, green: 0.969, blue: 0.984 },
    primary: { red: 0.357, green: 0.129, blue: 0.714 },
    secondary: { red: 0.745, green: 0.094, blue: 0.365 },
    text: { red: 0.102, green: 0.071, blue: 0.137 },
  },
  {
    id: 'coastal-teal',
    name: 'Coastal Teal',
    background: { red: 0.953, green: 0.980, blue: 0.980 },
    primary: { red: 0.059, green: 0.463, blue: 0.431 },
    secondary: { red: 0.082, green: 0.369, blue: 0.459 },
    text: { red: 0.043, green: 0.122, blue: 0.118 },
  },
  {
    id: 'precursor',
    name: 'Precursor',
    background: { red: 0.369, green: 0.192, blue: 0.086 },
    primary: { red: 1, green: 0.675, blue: 0.435 },
    secondary: { red: 0.176, green: 0.698, blue: 0.737 },
    text: { red: 1, green: 0.973, blue: 0.906 },
  },
]

export function toHexColor(color: AppearancePresetColor): string {
  const channel = (value: number) => Math.round(Math.min(1, Math.max(0, value)) * 255).toString(16).padStart(2, '0')
  return `#${channel(color.red)}${channel(color.green)}${channel(color.blue)}`
}

export const MAX_CUSTOM_APPEARANCE_THEMES = 24
export const MAX_CUSTOM_APPEARANCE_THEME_NAME_LENGTH = 40

export function customThemePreset(theme: CustomAppearanceTheme): AppearancePreset {
  return {
    id: theme.id,
    name: theme.name,
    background: { red: theme.backgroundColorRed, green: theme.backgroundColorGreen, blue: theme.backgroundColorBlue },
    primary: { red: theme.primaryColorRed, green: theme.primaryColorGreen, blue: theme.primaryColorBlue },
    secondary: { red: theme.secondaryColorRed, green: theme.secondaryColorGreen, blue: theme.secondaryColorBlue },
    text: { red: theme.textColorRed, green: theme.textColorGreen, blue: theme.textColorBlue },
  }
}

export function customThemeNameError(rawName: string, customThemes: readonly CustomAppearanceTheme[]): string | null {
  const name = rawName.trim()
  if (name.length === 0) return 'Enter a theme name.'
  if ([...name].length > MAX_CUSTOM_APPEARANCE_THEME_NAME_LENGTH) {
    return `Theme names can be up to ${MAX_CUSTOM_APPEARANCE_THEME_NAME_LENGTH} characters.`
  }
  const folded = name.toLocaleLowerCase()
  const existingNames = [...APPEARANCE_PRESETS.map((preset) => preset.name), ...customThemes.map((theme) => theme.name)]
  if (existingNames.some((existingName) => existingName.toLocaleLowerCase() === folded)) {
    return 'A theme with that name already exists.'
  }
  return null
}
