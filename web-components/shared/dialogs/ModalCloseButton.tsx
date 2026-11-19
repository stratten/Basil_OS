import { useEffect, useRef } from 'react'
import { WindowControlButton } from '../windowChrome/WindowControlButton'
import './modal-header.css'

interface ModalCloseButtonProps {
  onClose: () => void
  /** True while the dialog is doing work and must not be dismissed: the button is disabled and Escape does nothing. */
  disabled?: boolean
  /** False when the host already handles Escape itself, as BasilModalDialog does. */
  closeOnEscape?: boolean
  label?: string
}

/**
 * The circular window-control close button every Basil modal shows at the top left of its header, and the Escape key that does the same thing.
 * ModalHeader builds on it; a dialog with its own header layout, such as a wizard with an icon and a progress bar, places it first in that header.
 * Escape is ignored when another handler already took the key (for example an open menu), and the listener is removed when the dialog unmounts.
 */
export function ModalCloseButton({ onClose, disabled = false, closeOnEscape = true, label = 'Close' }: ModalCloseButtonProps) {
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!closeOnEscape || disabled) return undefined
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      event.stopPropagation()
      onCloseRef.current()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [closeOnEscape, disabled])

  return <WindowControlButton kind="close" label={label} className="basil-modal-close" disabled={disabled} onClick={onClose} />
}
