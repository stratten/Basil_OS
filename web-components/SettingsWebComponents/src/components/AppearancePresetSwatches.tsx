import { APPEARANCE_PRESETS, toHexColor, type AppearancePreset } from '../data/appearancePresets'

interface AppearancePresetSwatchesProps {
  onSelect: (preset: AppearancePreset) => void
}

export function AppearancePresetSwatches({ onSelect }: AppearancePresetSwatchesProps) {
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
          <span className="appearance-preset-swatch-bg" style={{ backgroundColor: toHexColor(preset.background) }}>
            <span className="appearance-preset-swatch-primary" style={{ backgroundColor: toHexColor(preset.primary) }} />
            <span className="appearance-preset-swatch-secondary" style={{ backgroundColor: toHexColor(preset.secondary) }} />
          </span>
          <span className="appearance-preset-swatch-name">{preset.name}</span>
        </button>
      ))}
    </div>
  )
}
