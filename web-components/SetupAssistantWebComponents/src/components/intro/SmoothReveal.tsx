import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'

// Matches the agent task sidebar motion: size eases over 400ms, content fades in after the space starts opening.
const REVEAL_EASING = 'cubic-bezier(0.2, 0.8, 0.2, 1)'
const REVEAL_SIZE_MS = 400
const REVEAL_FADE_MS = 200
const REVEAL_FADE_DELAY_MS = 100

interface SmoothRevealProps {
  open: boolean
  children: ReactNode
  className?: string
  /** Animate the first open when mounted already open, instead of rendering expanded immediately. */
  appear?: boolean
}

function isAnimatingSize(node: HTMLElement): boolean {
  return node.getAnimations().some(
    animation => (animation as CSSTransition).transitionProperty === 'grid-template-rows'
      && animation.playState === 'running',
  )
}

/**
 * Height-animated disclosure for content that appears in response to a choice.
 *
 * Content stays mounted through the closing transition (rendering the last open children) so it glides shut instead of vanishing, and is unmounted once the grid-row transition ends. Collapsed content is inert and hidden from assistive technology so hidden inputs cannot take focus.
 */
export function SmoothReveal({ open, children, className, appear = false }: SmoothRevealProps) {
  const [isMounted, setIsMounted] = useState(open)
  const [isExpanded, setIsExpanded] = useState(open && !appear)
  // Clipping is only needed mid-transition; once settled open, focus rings and select popovers must not be cut off.
  const [isSettledOpen, setIsSettledOpen] = useState(open && !appear)
  const containerRef = useRef<HTMLDivElement>(null)
  const lastOpenChildren = useRef<ReactNode>(children)
  if (open) lastOpenChildren.current = children
  const openRef = useRef(open)
  openRef.current = open

  // React 18 has no onTransitionCancel prop; an interrupted close must still unmount. Reversing a transition also cancels the old one, so only finish when no replacement size transition is running.
  useEffect(() => {
    const node = containerRef.current
    if (!node) return
    const handleCancel = (event: TransitionEvent) => {
      if (event.target !== node || event.propertyName !== 'grid-template-rows') return
      if (openRef.current) return
      if (typeof node.getAnimations === 'function' && isAnimatingSize(node)) return
      setIsMounted(false)
    }
    node.addEventListener('transitioncancel', handleCancel)
    return () => node.removeEventListener('transitioncancel', handleCancel)
  }, [isMounted])

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

  useLayoutEffect(() => {
    if (!open || !isMounted || isExpanded) return
    if (prefersReducedMotion()) {
      setIsSettledOpen(true)
    } else {
      // Reading layout commits the collapsed style, so switching to expanded starts a real transition instead of replacing the initial style.
      void containerRef.current?.offsetHeight
    }
    setIsExpanded(true)
  }, [open, isMounted, isExpanded])

  // A state change that lands before the section was ever styled produces no transition, so transitionend never fires. getAnimations() flushes the pending style, so if the browser is not animating the size, finish directly.
  useEffect(() => {
    if (!isMounted || open !== isExpanded) return
    if (open && isSettledOpen) return
    const node = containerRef.current
    if (!node || typeof node.getAnimations !== 'function') return
    if (isAnimatingSize(node)) return
    if (open) setIsSettledOpen(true)
    else setIsMounted(false)
  }, [open, isMounted, isExpanded, isSettledOpen])

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
