import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ModalHeader } from './ModalHeader'
import './basil-modal-dialog.css'

interface BasilModalDialogProps {
  title: string
  children: ReactNode
  /** Called for Escape and for a click on the backdrop. The dialog's own buttons call it themselves. */
  onClose: () => void
  testId?: string
  /** A wider card for content such as a review table. */
  size?: 'default' | 'wide'
  /** False while the dialog is doing work or asking for a decision: Escape and a backdrop click then do nothing, and only the dialog's own buttons close it. */
  dismissible?: boolean
  /** What the close button does. A dialog that is not dismissible has no close button unless it names one here, the same action its own Cancel button takes (for example cancel the running job, or discard a draft under review). `disabled` grays out the button while that action is unavailable. A dismissible dialog closes with `onClose` unless this says otherwise. */
  closeAction?: { onClick: () => void; disabled?: boolean }
}

const WINDOW_SURFACE_SELECTOR = '.basil-webkit-window-surface'

/**
 * A modal drawn exactly like the agent task "input needed" dialog (see shared/dialogs/basil-modal-dialog.css).
 * It is portaled into the Basil window surface when there is one, so the dimmed backdrop takes the window's rounded clip instead of covering the transparent area around it, and falls back to the document body anywhere else.
 */
export function BasilModalDialog({ title, children, onClose, testId, size = 'default', dismissible = true, closeAction }: BasilModalDialogProps) {
  const closeButtonAction = closeAction ?? (dismissible ? { onClick: onClose } : null)
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const dismissibleRef = useRef(dismissible)
  dismissibleRef.current = dismissible
  const [portalTarget] = useState<HTMLElement>(() => document.querySelector<HTMLElement>(WINDOW_SURFACE_SELECTOR) ?? document.body)

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        if (dismissibleRef.current) onCloseRef.current()
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      previouslyFocused?.focus?.()
    }
  }, [])

  return createPortal(
    <div
      className={portalTarget === document.body ? 'basil-modal-backdrop basil-modal-backdrop--viewport' : 'basil-modal-backdrop'}
      data-testid={testId}
      onMouseDown={event => {
        if (dismissible && event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className={size === 'wide' ? 'basil-modal-dialog basil-modal-dialog--panel basil-modal-dialog--wide' : 'basil-modal-dialog basil-modal-dialog--panel'}
        role="dialog"
        aria-modal="true"
        aria-labelledby="basil-modal-title"
        tabIndex={-1}
      >
        <ModalHeader
          title={title}
          titleId="basil-modal-title"
          onClose={closeButtonAction?.onClick ?? onClose}
          closeDisabled={closeButtonAction?.disabled ?? false}
          closeHidden={closeButtonAction === null}
          closeOnEscape={false}
        />
        <div className="basil-modal-body">{children}</div>
      </div>
    </div>,
    portalTarget,
  )
}
