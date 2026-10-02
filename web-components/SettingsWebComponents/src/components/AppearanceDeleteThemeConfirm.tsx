import type { CustomAppearanceTheme } from '../types'

interface AppearanceDeleteThemeConfirmProps {
  theme: CustomAppearanceTheme
  isDeleting: boolean
  errorMessage: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function AppearanceDeleteThemeConfirm({
  theme,
  isDeleting,
  errorMessage,
  onConfirm,
  onCancel,
}: AppearanceDeleteThemeConfirmProps) {
  return (
    <div className="appearance-delete-theme-confirm" role="group" aria-label={`Confirm deleting ${theme.name}`}>
      <p className="appearance-delete-theme-message">
        Delete “{theme.name}”? Your current colors stay as they are.
      </p>
      <div className="appearance-delete-theme-actions">
        <button type="button" className="appearance-theme-delete-confirm-button" disabled={isDeleting} onClick={onConfirm}>
          {isDeleting ? 'Deleting…' : 'Delete'}
        </button>
        <button type="button" className="secondary-button" disabled={isDeleting} onClick={onCancel}>
          Cancel
        </button>
      </div>
      {errorMessage && <p className="appearance-save-theme-error" role="alert">{errorMessage}</p>}
    </div>
  )
}
