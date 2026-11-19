interface AppearanceSaveBarProps {
  hasUnsavedChanges: boolean
  isSaving: boolean
  isCanceling: boolean
  errorMessage: string | null
  onSave: () => void
  onCancel: () => void
  onReset: () => void
}

export function AppearanceSaveBar({
  hasUnsavedChanges,
  isSaving,
  isCanceling,
  errorMessage,
  onSave,
  onCancel,
  onReset,
}: AppearanceSaveBarProps) {
  const isBusy = isSaving || isCanceling

  return (
    <div className="appearance-save-bar">
      <div className="appearance-save-bar-buttons">
        <button type="button" className="primary-button" onClick={onSave} disabled={!hasUnsavedChanges || isBusy}>
          {isSaving ? 'Saving…' : 'Save Changes'}
        </button>
        <button type="button" className="secondary-button" onClick={onCancel} disabled={!hasUnsavedChanges || isBusy}>
          {isCanceling ? 'Canceling…' : 'Cancel Changes'}
        </button>
        <button type="button" className="bordered-button appearance-reset-button" onClick={onReset} disabled={isBusy}>
          Reset to Default Colors
        </button>
      </div>
      {errorMessage && (
        <p className="appearance-save-bar-error" role="alert">{errorMessage}</p>
      )}
      {!errorMessage && hasUnsavedChanges && (
        <p className="appearance-save-bar-hint">You have unsaved changes. Save to apply them or cancel to revert to the previous settings.</p>
      )}
      {!errorMessage && !hasUnsavedChanges && (
        <p className="appearance-save-bar-hint appearance-save-bar-hint-saved">All changes have been saved.</p>
      )}
    </div>
  )
}
