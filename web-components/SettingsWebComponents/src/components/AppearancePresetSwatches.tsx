import { APPEARANCE_PRESETS, customThemePreset, toHexColor, type AppearancePreset } from '../data/appearancePresets'
import type { CustomAppearanceTheme } from '../types'

interface AppearancePresetSwatchesProps {
  onSelect: (preset: AppearancePreset) => void
  customThemes?: readonly CustomAppearanceTheme[]
  onSelectCustom?: (theme: CustomAppearanceTheme) => void
  onRequestDeleteCustom?: (theme: CustomAppearanceTheme) => void
  deleteDisabled?: boolean
}

function AppearancePresetSwatchFace({ preset }: { preset: AppearancePreset }) {
  return (
    <>
      <span className="appearance-preset-swatch-bg" style={{ backgroundColor: toHexColor(preset.background) }}>
        <span className="appearance-preset-swatch-primary" style={{ backgroundColor: toHexColor(preset.primary) }} />
        <span className="appearance-preset-swatch-secondary" style={{ backgroundColor: toHexColor(preset.secondary) }} />
      </span>
      <span className="appearance-preset-swatch-name">{preset.name}</span>
    </>
  )
}

export function AppearancePresetSwatches({
  onSelect,
  customThemes = [],
  onSelectCustom,
  onRequestDeleteCustom,
  deleteDisabled = false,
}: AppearancePresetSwatchesProps) {
  return (
    <div className="appearance-preset-swatches" role="group" aria-label="Preset color palettes">
      {APPEARANCE_PRESETS.map((preset) => (
        <button
          key={preset.id}
          type="button"
          className="appearance-preset-swatch"
          title={preset.name}
          aria-label={preset.name}
          onClick={() => onSelect(preset)}
        >
          <AppearancePresetSwatchFace preset={preset} />
        </button>
      ))}
      {customThemes.map((theme) => (
        <div key={theme.id} className="appearance-preset-swatch-item">
          <button
            type="button"
            className="appearance-preset-swatch"
            title={theme.name}
            aria-label={theme.name}
            onClick={() => onSelectCustom?.(theme)}
          >
            <AppearancePresetSwatchFace preset={customThemePreset(theme)} />
          </button>
          {onRequestDeleteCustom && (
            <button
              type="button"
              className="appearance-preset-swatch-delete"
              title={`Delete ${theme.name}`}
              aria-label={`Delete theme ${theme.name}`}
              disabled={deleteDisabled}
              onClick={() => onRequestDeleteCustom(theme)}
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
