import type {
  SetupActionExecutionItem,
  SetupAppearanceChangeRow,
  SetupAppearanceChangeSummary,
} from '@/types'

interface ColorGroup {
  label: string
  keys: readonly [string, string, string]
}

const COLOR_GROUPS: readonly ColorGroup[] = [
  { label: 'Background', keys: ['background_color_red', 'background_color_green', 'background_color_blue'] },
  { label: 'Primary accent', keys: ['primary_color_red', 'primary_color_green', 'primary_color_blue'] },
  { label: 'Secondary accent', keys: ['secondary_color_red', 'secondary_color_green', 'secondary_color_blue'] },
  { label: 'Text', keys: ['text_color_red', 'text_color_green', 'text_color_blue'] },
  { label: 'Processing', keys: ['processing_color_red', 'processing_color_green', 'processing_color_blue'] },
  {
    label: 'Processing accent',
    keys: ['processing_accent_color_red', 'processing_accent_color_green', 'processing_accent_color_blue'],
  },
]

export function buildAppearanceChangeSummary(
  result: SetupActionExecutionItem | undefined,
): SetupAppearanceChangeSummary | null {
  if (!result || result.kind !== 'update_settings') return null

  const uiChanges = result.result_payload.ui_changes
  const appearanceSettings = result.result_payload.appearance_settings
  if (!Array.isArray(uiChanges) || uiChanges.length === 0) return null
  if (!isRecord(appearanceSettings)) return null

  const changedKeys = new Set<string>()
  const oldValueByKey = new Map<string, unknown>()
  for (const change of uiChanges) {
    if (!isUiChange(change)) continue
    const key = change.path.slice('ui.'.length)
    changedKeys.add(key)
    oldValueByKey.set(key, change.old_value)
  }

  const rows: SetupAppearanceChangeRow[] = []
  for (const group of COLOR_GROUPS) {
    if (!group.keys.some(key => changedKeys.has(key))) continue

    const newColor = channelsToCss(group.keys.map(key => colorChannel(appearanceSettings[key])))
    const oldColor = channelsToCss(
      group.keys.map(key => colorChannel(changedKeys.has(key) ? oldValueByKey.get(key) : appearanceSettings[key])),
    )
    if (!oldColor || !newColor) continue
    rows.push({ kind: 'color', label: group.label, oldColor, newColor })
  }

  if (changedKeys.has('preferred_font')) {
    const oldFont = oldValueByKey.get('preferred_font')
    const newFont = appearanceSettings.preferred_font
    if (typeof oldFont === 'string' && typeof newFont === 'string') {
      rows.push({ kind: 'font', label: 'Font', oldFont, newFont })
    }
  }

  if (rows.length === 0) return null
  return {
    rows,
    contrastWarning: toContrastWarning(result.result_payload.contrast_warning),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isUiChange(value: unknown): value is { path: string; old_value: unknown } {
  return isRecord(value)
    && typeof value.path === 'string'
    && value.path.startsWith('ui.')
    && 'old_value' in value
}

function colorChannel(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null
}

function channelsToCss(channels: Array<number | null>): string | null {
  if (channels.some(channel => channel === null)) return null
  const [red, green, blue] = channels as number[]
  return `rgb(${Math.round(red * 255)}, ${Math.round(green * 255)}, ${Math.round(blue * 255)})`
}

function toContrastWarning(value: unknown): SetupAppearanceChangeSummary['contrastWarning'] {
  if (!isRecord(value)) return null
  const { ratio, required_ratio: requiredRatio } = value
  if (
    typeof ratio !== 'number'
    || !Number.isFinite(ratio)
    || typeof requiredRatio !== 'number'
    || !Number.isFinite(requiredRatio)
  ) return null
  return { ratio, requiredRatio }
}
