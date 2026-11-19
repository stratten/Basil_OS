import type { ReactNode } from 'react'
import { ModalHeader } from '@shared/dialogs/ModalHeader'

interface SettingsModalCardProps {
  title: string
  /** Names the dialog for assistive technology; defaults to the title. */
  ariaLabel?: string
  /** The close button's action. A modal's own Cancel and Back buttons stay in its body and keep calling what they call today. */
  onClose: () => void
  /** True while the modal is doing work that closing would interrupt. */
  closeDisabled?: boolean
  /** The quiet line under the title. */
  subtitle?: ReactNode
  subtitleClassName?: string
  /** Extra class on the card, for a modal that needs its own width or spacing. */
  className?: string
  children: ReactNode
}

/**
 * The card every Settings modal draws inside the overlay: the shared header (close button at the top left, then the title) above a body that scrolls on its own.
 * The header never scrolls away, so a long form can always be closed without scrolling to its bottom.
 */
export function SettingsModalCard({ title, ariaLabel, onClose, closeDisabled = false, subtitle, subtitleClassName, className, children }: SettingsModalCardProps) {
  return (
    <div className={className ? `connections-add-modal ${className}` : 'connections-add-modal'} role="dialog" aria-modal="true" aria-label={ariaLabel ?? title}>
      <ModalHeader title={title} titleClassName="connections-add-modal-title" onClose={onClose} closeDisabled={closeDisabled} />
      <div className="connections-add-modal-body">
        {subtitle ? <p className={subtitleClassName ? `connections-add-modal-subtitle ${subtitleClassName}` : 'connections-add-modal-subtitle'}>{subtitle}</p> : null}
        {children}
      </div>
    </div>
  )
}
