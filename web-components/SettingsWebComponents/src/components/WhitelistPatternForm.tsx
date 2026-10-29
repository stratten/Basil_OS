import { useState } from 'react'
import type { WhitelistPatternFields } from '../types'

interface WhitelistPatternFormProps {
  editingPattern: WhitelistPatternFields | null
  disabled: boolean
  onSubmit: (pattern: string, patternType: string, description: string) => void
  onCancel: () => void
}

const PATTERN_TYPES = ['exact', 'prefix', 'regex'] as const

function validate(pattern: string, patternType: string): string | null {
  if (!pattern.trim()) return 'Pattern cannot be empty.'
  if (patternType === 'regex') {
    try {
      new RegExp(pattern)
    } catch (error) {
      return `Invalid regular expression: ${(error as Error).message}`
    }
  }
  return null
}

export function WhitelistPatternForm({ editingPattern, disabled, onSubmit, onCancel }: WhitelistPatternFormProps) {
  const [pattern, setPattern] = useState(editingPattern?.pattern ?? '')
  const [patternType, setPatternType] = useState<string>(editingPattern?.patternType ?? 'exact')
  const [description, setDescription] = useState(editingPattern?.description ?? '')
  const [validationError, setValidationError] = useState<string | null>(null)

  function handleSubmit() {
    const error = validate(pattern, patternType)
    if (error) {
      setValidationError(error)
      return
    }
    onSubmit(pattern, patternType, description)
  }

  return (
    <div className="permissions-whitelist-form">
      <label>
        Command Pattern
        <input type="text" value={pattern} disabled={disabled} onChange={(event) => { setPattern(event.target.value); setValidationError(null) }} placeholder="e.g. git status" />
      </label>
      <fieldset className="permissions-pattern-type-picker">
        <legend>Pattern type</legend>
        <div className="permissions-pattern-type-options">
          {PATTERN_TYPES.map((type) => (
            <label key={type} className={`permissions-pattern-type-option${patternType === type ? ' permissions-pattern-type-option-selected' : ''}`}>
              <input type="radio" name="patternType" disabled={disabled} checked={patternType === type} onChange={() => { setPatternType(type); setValidationError(null) }} />
              {type}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        Description (optional)
        <input type="text" value={description} disabled={disabled} onChange={(event) => setDescription(event.target.value)} placeholder="What does this command do?" />
      </label>
      {validationError && <p className="permissions-whitelist-form-error">{validationError}</p>}
      <div className="permissions-whitelist-form-actions">
        <button type="button" className="secondary-button" disabled={disabled} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="primary-button" onClick={handleSubmit} disabled={disabled || !pattern.trim()}>
          {disabled ? 'Saving…' : editingPattern ? 'Save Changes' : 'Add Pattern'}
        </button>
      </div>
    </div>
  )
}
