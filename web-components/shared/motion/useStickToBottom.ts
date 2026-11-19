import { type RefObject, useCallback, useLayoutEffect, useRef, useState } from 'react'

const STICK_THRESHOLD_PX = 48

export interface StickToBottom {
  /** True while the region follows its newest content: the reader is at (or near) the bottom. */
  isPinned: boolean
  /** Scrolls to the newest content and re-engages the pin. */
  scrollToBottom: () => void
}

// Keeps a scroll region pinned to its newest content while the user is already at (or near) the bottom. Scrolling up releases the pin; returning to the bottom re-engages it. The return value lets a caller show a "jump to latest" control while the pin is released.
export function useStickToBottom(
  scrollRef: RefObject<HTMLElement>,
  contentRef: RefObject<HTMLElement>,
): StickToBottom {
  const [isPinned, setIsPinned] = useState(true)
  const pinnedRef = useRef(true)

  const applyPinned = useCallback((next: boolean) => {
    pinnedRef.current = next
    setIsPinned(current => (current === next ? current : next))
  }, [])

  useLayoutEffect(() => {
    const scroller = scrollRef.current
    const content = contentRef.current
    if (!scroller || !content || typeof ResizeObserver === 'undefined') return undefined

    let lastScrollTop = scroller.scrollTop
    // Only upward movement releases the pin: a scroll event can be dispatched after later content growth has already been laid out, which would otherwise read as the user leaving the bottom.
    const updatePinned = () => {
      const scrollTop = scroller.scrollTop
      if (scroller.scrollHeight - scrollTop - scroller.clientHeight <= STICK_THRESHOLD_PX) applyPinned(true)
      else if (scrollTop < lastScrollTop) applyPinned(false)
      lastScrollTop = scrollTop
    }
    const observer = new ResizeObserver(() => {
      if (pinnedRef.current) scroller.scrollTop = scroller.scrollHeight
    })

    scroller.addEventListener('scroll', updatePinned, { passive: true })
    observer.observe(content)
    observer.observe(scroller)
    return () => {
      observer.disconnect()
      scroller.removeEventListener('scroll', updatePinned)
    }
  }, [scrollRef, contentRef, applyPinned])

  const scrollToBottom = useCallback(() => {
    const scroller = scrollRef.current
    if (!scroller) return
    applyPinned(true)
    scroller.scrollTop = scroller.scrollHeight
  }, [scrollRef, applyPinned])

  return { isPinned, scrollToBottom }
}
