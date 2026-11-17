import { ignoreLabelClickWhileSelectingText } from './labelTextSelection'

interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  ariaLabel?: string
  disabled?: boolean
  id?: string
}

export function Switch({ checked, onChange, label, ariaLabel, disabled, id }: SwitchProps) {
  return (
    <label
      className={disabled ? 'basil-switch basil-switch--disabled' : 'basil-switch'}
      htmlFor={id}
      onClick={ignoreLabelClickWhileSelectingText}
    >
      <input
        id={id}
        type="checkbox"
        className="basil-switch-input"
        checked={checked}
        aria-label={ariaLabel}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  )
}
