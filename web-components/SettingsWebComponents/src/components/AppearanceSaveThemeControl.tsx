import { useEffect, useRef, useState, type FormEvent } from 'react'
import { MAX_CUSTOM_APPEARANCE_THEMES, customThemeNameError } from '../data/appearancePresets'
import type { CustomAppearanceTheme } from '../types'

interface AppearanceSaveThemeControlProps {
  customThemes: readonly CustomAppearanceTheme[]
  isSaving: boolean
  isBusy: boolean
  errorMessage: string | null
  onSave: (name: string, onSaved: () => void) => void
  onDismissError: () => void
}

export function AppearanceSaveThemeControl({
  customThemes,
  isSaving,
  isBusy,
  errorMessage,
  onSave,
  onDismissError,
}: AppearanceSaveThemeControlProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [name, setName] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const limitReached = customThemes.length >= MAX_CUSTOM_APPEARANCE_THEMES

  useEffect(() => {
    if (isEditing) inputRef.current?.focus()
  }, [isEditing])

  function close() {
    setIsEditing(false)
    setName('')
    setValidationError(null)
    onDismissError()
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isBusy) return
    const error = customThemeNameError(name, customThemes)
    setValidationError(error)
    if (error) return
    onSave(name.trim(), close)
  }

  if (!isEditing) {
    return (
      <div className="appearance-save-theme">
        <button
          type="button"
          className="secondary-button"
          disabled={limitReached || isBusy}
          onClick={() => setIsEditing(true)}
        >
          Save as Theme
        </button>
        {limitReached && (
          <p className="appearance-save-theme-hint">
            You can save up to {MAX_CUSTOM_APPEARANCE_THEMES} custom themes. Delete one to save another.
          </p>
        )}
      </div>
    )
  }

  const message = validationError ?? errorMessage
  return (
    <form className="appearance-save-theme" onSubmit={handleSubmit}>
      <label htmlFor="appearance-save-theme-name" className="appearance-save-theme-label">Theme Name:</label>
      <input
        ref={inputRef}
        id="appearance-save-theme-name"
        type="text"
        value={name}
        disabled={isSaving}
        onChange={(event) => {
          setName(event.target.value)
          setValidationError(null)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !isSaving) {
            event.preventDefault()
            close()
          }
        }}
      />
      <button type="submit" className="primary-button" disabled={isBusy}>
        {isSaving ? 'Saving…' : 'Save'}
      </button>
      <button type="button" className="secondary-button" disabled={isSaving} onClick={close}>
        Cancel
      </button>
      {message && <p className="appearance-save-theme-error" role="alert">{message}</p>}
    </form>
  )
}
