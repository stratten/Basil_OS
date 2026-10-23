interface StringListEditorProps {
  label: string
  values: string[]
  placeholder: string
  maxCount: number
  disabled?: boolean
  onChange: (values: string[]) => void
}

export function StringListEditor({ label, values, placeholder, maxCount, disabled, onChange }: StringListEditorProps) {
  function updateAt(index: number, value: string) {
    const next = values.slice()
    next[index] = value
    onChange(next)
  }

  function removeAt(index: number) {
    onChange(values.filter((_, i) => i !== index))
  }

  function add() {
    if (values.length >= maxCount) return
    onChange([...values, ''])
  }

  return (
    <div className="string-list-editor">
      <div className="string-list-editor-header">
        <span className="string-list-editor-label">{label}</span>
        <button
          type="button"
          className="secondary-button string-list-editor-add"
          disabled={disabled || values.length >= maxCount}
          onClick={add}
        >
          + Add
        </button>
      </div>
      {values.length === 0 ? (
        <p className="string-list-editor-empty">None configured.</p>
      ) : (
        values.map((value, index) => (
          <div key={index} className="string-list-editor-row">
            <input
              type="text"
              className="string-list-editor-input"
              placeholder={placeholder}
              value={value}
              disabled={disabled}
              onChange={(event) => updateAt(index, event.target.value)}
            />
            <button
              type="button"
              className="string-list-editor-remove"
              disabled={disabled}
              aria-label={`Remove ${label} entry ${index + 1}`}
              onClick={() => removeAt(index)}
            >
              &minus;
            </button>
          </div>
        ))
      )}
    </div>
  )
}

export function cleanedStringList(values: string[]): string[] {
  return values.map((value) => value.trim()).filter((value) => value.length > 0)
}

export function optionalTrimmed(value: string): string | undefined {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : undefined
}
