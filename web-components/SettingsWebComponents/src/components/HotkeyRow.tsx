import { getBindingCapSymbols, HotkeyKeyCap } from './HotkeyKeyCap'
import type { HotkeyRowSnapshot } from '../types'

interface HotkeyRowProps {
  row: HotkeyRowSnapshot
  isEditing: boolean
  isSaving: boolean
  isDisabled: boolean
  errorMessage: string | null
  onEdit: () => void
  onCancel: () => void
}

export function HotkeyRow({ row, isEditing, isSaving, isDisabled, errorMessage, onEdit, onCancel }: HotkeyRowProps) {
  const capSymbols = getBindingCapSymbols(row.binding)

  return (
    <div className="hotkey-row">
      <div className="hotkey-row-main">
        <div className="hotkey-row-labels">
          <span className="hotkey-row-title">{row.title}</span>
          {row.subtitle && <span className="hotkey-row-subtitle">{row.subtitle}</span>}
        </div>

        <div className="hotkey-row-controls">
          {isEditing ? (
            <>
              <span className="hotkey-row-recording-indicator">Press key...</span>
              <button type="button" className="secondary-button" onClick={onCancel}>Cancel</button>
            </>
          ) : (
            <>
              {capSymbols.map((symbol, index) => (
                <HotkeyKeyCap key={`${row.id}-cap-${index}`} symbol={symbol} />
              ))}
              <button type="button" className="secondary-button" onClick={onEdit} disabled={isSaving || isDisabled}>
                {isSaving ? 'Saving...' : 'Edit'}
              </button>
            </>
          )}
        </div>
      </div>

      {errorMessage && (
        <p className="hotkey-row-error" role="alert">{errorMessage}</p>
      )}
    </div>
  )
}
