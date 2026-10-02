export interface PolicyRadioOption<T extends string> {
  id: T
  label: string
  description?: string
}

interface PolicyRadioGroupProps<T extends string> {
  legend: string
  name: string
  options: readonly PolicyRadioOption<T>[]
  value: T
  disabled?: boolean
  onChange: (value: T) => void
}

export function PolicyRadioGroup<T extends string>({ legend, name, options, value, disabled, onChange }: PolicyRadioGroupProps<T>) {
  const selected = options.find((option) => option.id === value)
  // WebKit double-counts a fieldset legend when the fieldset is itself a flex item, leaving blank space at the bottom of the card until the next re-layout.
  return (
    <div className="browser-automation-fieldset-frame">
      <fieldset className="browser-automation-fieldset">
        <legend>{legend}</legend>
        <div className="browser-automation-radio-list">
          {options.map((option) => (
            <label key={option.id} className="browser-automation-radio-option">
              <input
                type="radio"
                name={name}
                value={option.id}
                checked={option.id === value}
                disabled={disabled}
                onChange={() => onChange(option.id)}
              />
              {option.label}
            </label>
          ))}
        </div>
        {selected?.description && <p className="browser-automation-field-hint">{selected.description}</p>}
      </fieldset>
    </div>
  )
}
