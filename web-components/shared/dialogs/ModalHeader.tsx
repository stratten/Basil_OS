import { ModalCloseButton } from './ModalCloseButton'
import './modal-header.css'

interface ModalHeaderProps {
  title: string
  /** Called by the close button and by Escape. A dialog's own Cancel or Back buttons stay where they are and call whatever they already call. */
  onClose: () => void
  /** Id for the title element, for the dialog's aria-labelledby. */
  titleId?: string
  /** Replaces the default title class when the host styles its own title. */
  titleClassName?: string
  /** True while the dialog is doing work and must not be dismissed: the close button is disabled and Escape does nothing. */
  closeDisabled?: boolean
  /** False when the host already handles Escape itself, as BasilModalDialog does. */
  closeOnEscape?: boolean
  /** True when the dialog has no way to be closed from its header, so no close button is drawn rather than a dead one. */
  closeHidden?: boolean
  closeLabel?: string
}

/**
 * The header every Basil modal shares: the circular window-control close button at the top left, with the title beside it, the same arrangement a Basil window header uses.
 * It sits above the dialog's scrolling body, so a long dialog never scrolls its close button out of reach.
 */
export function ModalHeader({ title, onClose, titleId, titleClassName = 'basil-modal-title', closeDisabled = false, closeOnEscape = true, closeHidden = false, closeLabel = 'Close' }: ModalHeaderProps) {
  return (
    <header className="basil-modal-header">
      {closeHidden ? null : <ModalCloseButton onClose={onClose} disabled={closeDisabled} closeOnEscape={closeOnEscape} label={closeLabel} />}
      <h3 id={titleId} className={titleClassName}>{title}</h3>
    </header>
  )
}
