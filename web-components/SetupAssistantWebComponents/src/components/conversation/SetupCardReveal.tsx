import { useState, type ReactNode } from 'react'

import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'

// Fades a decision card in while its height opens smoothly, so the content below it is eased out of the way instead of jumping by the full height of the card. The clip that makes the height animation possible is removed once the animation ends, so the card's shadow is never cut off at rest. `collapsed` closes the card the same way, for a surface that should leave without making what follows it jump.
export function SetupCardReveal({
  children,
  collapsed = false,
}: {
  children: ReactNode
  collapsed?: boolean
}) {
  const [settled, setSettled] = useState(() => prefersReducedMotion())
  const className = [
    'setup-card-reveal',
    settled ? 'is-settled' : '',
    collapsed ? 'is-collapsed' : '',
  ].filter(Boolean).join(' ')

  return (
    <div
      className={className}
      aria-hidden={collapsed || undefined}
      onAnimationEnd={event => {
        if (event.target === event.currentTarget) setSettled(true)
      }}
    >
      <div className="setup-card-reveal-inner">{children}</div>
    </div>
  )
}
