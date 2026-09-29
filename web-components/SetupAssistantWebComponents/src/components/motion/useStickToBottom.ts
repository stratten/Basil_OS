import { type RefObject, useLayoutEffect } from 'react'

const STICK_THRESHOLD_PX = 48

// Keeps a scroll region pinned to its newest content while the user is already at (or near) the bottom. Scrolling up releases the pin; returning to the bottom re-engages it.
export function useStickToBottom(
  scrollRef: RefObject<HTMLElement>,
  contentRef: RefObject<HTMLElement>,
): void {
  useLayoutEffect(() => {
    const scroller = scrollRef.current
    const content = contentRef.current
    if (!scroller || !content || typeof ResizeObserver === 'undefined') return undefined

    let isPinned = true
    let lastScrollTop = scroller.scrollTop
    // Only upward movement releases the pin: a scroll event can be dispatched after later content growth has already been laid out, which would otherwise read as the user leaving the bottom.
    const updatePinned = () => {
      const scrollTop = scroller.scrollTop
      if (scroller.scrollHeight - scrollTop - scroller.clientHeight <= STICK_THRESHOLD_PX) isPinned = true
      else if (scrollTop < lastScrollTop) isPinned = false
      lastScrollTop = scrollTop
    }
    const observer = new ResizeObserver(() => {
      if (isPinned) scroller.scrollTop = scroller.scrollHeight
    })

    scroller.addEventListener('scroll', updatePinned, { passive: true })
    observer.observe(content)
    observer.observe(scroller)
    return () => {
      observer.disconnect()
      scroller.removeEventListener('scroll', updatePinned)
    }
  }, [scrollRef, contentRef])
}
