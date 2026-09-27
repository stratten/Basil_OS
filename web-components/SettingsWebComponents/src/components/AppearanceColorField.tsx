import type { AppearanceColorFieldId, AppearanceColorPickerRequest } from '../types'

interface AppearanceColorFieldProps {
  id: string
  label: string
  fieldId: AppearanceColorFieldId
  red: number
  green: number
  blue: number
  onRequestPicker: (request: AppearanceColorPickerRequest) => void
}

function toHex(red: number, green: number, blue: number): string {
  const channel = (value: number) => Math.round(Math.min(1, Math.max(0, value)) * 255).toString(16).padStart(2, '0')
  return `#${channel(red)}${channel(green)}${channel(blue)}`
}

export function AppearanceColorField({ id, label, fieldId, red, green, blue, onRequestPicker }: AppearanceColorFieldProps) {
  const hex = toHex(red, green, blue)

  return (
    <div className="appearance-color-field">
      <span id={`${id}-label`} className="appearance-color-field-label">{label}</span>
      <button
        id={id}
        type="button"
        className="appearance-color-field-trigger"
        aria-labelledby={`${id}-label`}
        aria-label={`${label} ${hex.toUpperCase()}`}
        style={{ backgroundColor: hex }}
        onClick={() => onRequestPicker({ fieldId, red, green, blue })}
      />
      <span className="appearance-color-field-hex">{hex.toUpperCase()}</span>
    </div>
  )
}
