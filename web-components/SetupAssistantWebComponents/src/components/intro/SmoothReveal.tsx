import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

// Matches the agent task sidebar motion: size eases over 400ms, content fades in after the space starts opening.
const REVEAL_EASING = 'cubic-bezier(0.2, 0.8, 0.2, 1)'
const REVEAL_SIZE_MS = 400
const REVEAL_FADE_MS = 200
const REVEAL_FADE_DELAY_MS = 100

interface SmoothRevealProps {
  open: boolean
  children: ReactNode
  className?: string
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Height-animated disclosure for content that appears in response to a choice.
 *
 * Content stays mounted through the closing transition (rendering the last open children) so it glides shut instead of vanishing, and is unmounted once the grid-row transition ends. Collapsed content is inert and hidden from assistive technology so hidden inputs cannot take focus.
 */
export function SmoothReveal({ open, children, className }: SmoothRevealProps) {
  const [isMounted, setIsMounted] = useState(open)
  const [isExpanded, setIsExpanded] = useState(open)
  // Clipping is only needed mid-transition; once settled open, focus rings and select popovers must not be cut off.
  const [isSettledOpen, setIsSettledOpen] = useState(open)
  const containerRef = useRef<HTMLDivElement>(null)
  const lastOpenChildren = useRef<ReactNode>(children)
  if (open) lastOpenChildren.current = children

  useLayoutEffect(() => {
    if (open) {
      setIsMounted(true)
      return
    }
    setIsSettledOpen(false)
    if (prefersReducedMotion()) {
      setIsExpanded(false)
      setIsMounted(false)
      return
    }
    setIsExpanded(false)
  }, [open])

  useEffect(() => {
    if (!open || !isMounted || isExpanded) return
    if (prefersReducedMotion()) {
      setIsExpanded(true)
      setIsSettledOpen(true)
      return
    }
    // Let the collapsed frame paint first so the browser has a starting height to transition from.
    let innerFrame = 0
    const outerFrame = requestAnimationFrame(() => {
      innerFrame = requestAnimationFrame(() => setIsExpanded(true))
    })
    return () => {
      cancelAnimationFrame(outerFrame)
      cancelAnimationFrame(innerFrame)
    }
  }, [open, isMounted, isExpanded])

  useLayoutEffect(() => {
    const node = containerRef.current as (HTMLDivElement & { inert?: boolean }) | null
    if (node) node.inert = !open
  }, [open, isMounted])

  if (!isMounted) return null

  const reduceMotion = prefersReducedMotion()
  const containerStyle: CSSProperties = {
    display: 'grid',
    gridTemplateRows: isExpanded ? '1fr' : '0fr',
    opacity: isExpanded ? 1 : 0,
    transform: isExpanded ? 'none' : 'translateY(-4px)',
    transition: reduceMotion
      ? 'none'
      : [
          `grid-template-rows ${REVEAL_SIZE_MS}ms ${REVEAL_EASING}`,
          `transform ${REVEAL_SIZE_MS}ms ${REVEAL_EASING}`,
          `opacity ${REVEAL_FADE_MS}ms ease-out ${isExpanded ? REVEAL_FADE_DELAY_MS : 0}ms`,
        ].join(', '),
  }

  return (
    <div
      ref={containerRef}
      className={className}
      style={containerStyle}
      aria-hidden={!open}
      data-reveal-state={isExpanded ? 'open' : 'closed'}
      onTransitionEnd={event => {
        if (event.target !== event.currentTarget || event.propertyName !== 'grid-template-rows') return
        if (open) setIsSettledOpen(true)
        else setIsMounted(false)
      }}
    >
      <div style={{ minHeight: 0, overflow: isSettledOpen ? 'visible' : 'hidden' }}>
        {open ? children : lastOpenChildren.current}
      </div>
    </div>
  )
}

export default SmoothReveal
