import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { BasilCloudAccountPanel } from './BasilCloudAccountPanel'
import type { SetupAgentModelAccessOption } from '@/types'

interface Props {
  option: SetupAgentModelAccessOption
  refreshOptions: () => Promise<void>
  onClose: () => void
}

/** Holds the Basil Cloud sign-in, sign-up, and payment prompts in a dialog that only exists after the user chooses Basil Cloud. */
export function BasilCloudAccountModal({ option, refreshOptions, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      previouslyFocused?.focus?.()
    }
  }, [])

  const title = option.requires_sign_in ? 'Sign in to use Basil Cloud' : 'Add a payment method for Basil Cloud'

  return createPortal(
    <div
      className="basil-cloud-modal-backdrop"
      data-testid="basil-cloud-account-modal"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className="basil-cloud-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="basil-cloud-modal-title"
        tabIndex={-1}
      >
        <div className="basil-cloud-modal-header">
          <h3 id="basil-cloud-modal-title">{title}</h3>
          <button type="button" className="basil-cloud-modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <BasilCloudAccountPanel
          key={option.requires_sign_in ? 'sign-in' : 'payment'}
          option={option}
          refreshOptions={refreshOptions}
        />
      </div>
    </div>,
    document.body,
  )
}
