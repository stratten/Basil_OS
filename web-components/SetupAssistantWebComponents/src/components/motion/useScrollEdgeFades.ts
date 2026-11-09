import { type RefObject, useLayoutEffect } from 'react'

// Every internal scroll region in the setup window. A region added to the stylesheets with overflow-y: auto needs its selector here to get edge fades.
export const SCROLL_EDGE_FADE_SELECTOR = [
  '.setup-stage-frame',
  '.intro-step',
  '.orientation-scroll-region',
  '.basil-messages',
  '.conversation-observation-list',
  '.setup-agenda-sidebar-body',
  '.setup-agenda-collapsed-dot-strip',
  '.setup-workspace > .artifact-panel',
  '.inline-email-context-body',
  '.inline-dill-draft-body',
].join(', ')

const EDGE_TOLERANCE_PX = 2
// Matches the fade depth the stylesheet gives a region with plenty of hidden content.
const MAX_FADE_PX = 32
const FADE_TOP_PROPERTY = '--setup-scroll-fade-top'
const FADE_BOTTOM_PROPERTY = '--setup-scroll-fade-bottom'

function setFadeDepth(element: HTMLElement, property: string, hiddenPx: number): void {
  // The fade is never deeper than the content actually hidden, so a region that is only a few pixels short of its end barely fades instead of dimming the last lines the reader can see.
  if (hiddenPx > EDGE_TOLERANCE_PX) element.style.setProperty(property, `${Math.min(MAX_FADE_PX, Math.round(hiddenPx))}px`)
  else element.style.removeProperty(property)
}

export function updateScrollEdgeAttributes(element: HTMLElement): void {
  const hiddenAbovePx = element.scrollTop
  const hiddenBelowPx = element.scrollHeight - element.clientHeight - element.scrollTop
  element.toggleAttribute('data-overflow-top', hiddenAbovePx > EDGE_TOLERANCE_PX)
  element.toggleAttribute('data-overflow-bottom', hiddenBelowPx > EDGE_TOLERANCE_PX)
  setFadeDepth(element, FADE_TOP_PROPERTY, hiddenAbovePx)
  setFadeDepth(element, FADE_BOTTOM_PROPERTY, hiddenBelowPx)
}

// Marks each scroll region under the root with data-overflow-top / data-overflow-bottom so CSS can fade the edge where content continues out of view.
export function useScrollEdgeFades(rootRef: RefObject<HTMLElement>): void {
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root || typeof ResizeObserver === 'undefined' || typeof MutationObserver === 'undefined') return undefined

    const tracked = new Set<HTMLElement>()
    const updateAll = () => tracked.forEach(updateScrollEdgeAttributes)
    // Children are observed too: streamed text and expanding reveals grow the content while the region's own box stays the same size.
    const resizeObserver = new ResizeObserver(updateAll)
    const syncTracked = () => {
      resizeObserver.disconnect()
      tracked.clear()
      root.querySelectorAll<HTMLElement>(SCROLL_EDGE_FADE_SELECTOR).forEach(element => {
        tracked.add(element)
        resizeObserver.observe(element)
        Array.from(element.children).forEach(child => resizeObserver.observe(child))
      })
      updateAll()
    }
    const mutationObserver = new MutationObserver(records => {
      if (records.some(record => record.type === 'childList')) syncTracked()
      else updateAll()
    })
    const handleScroll = (event: Event) => {
      const target = event.target
      if (target instanceof HTMLElement && tracked.has(target)) updateScrollEdgeAttributes(target)
    }

    // A reveal animation or transition can move a region's scroll extent without resizing any observed box, so re-measure when one finishes.
    const handleMotionEnd = () => updateAll()

    syncTracked()
    mutationObserver.observe(root, { characterData: true, childList: true, subtree: true })
    root.addEventListener('scroll', handleScroll, { capture: true, passive: true })
    root.addEventListener('animationend', handleMotionEnd)
    root.addEventListener('transitionend', handleMotionEnd)
    return () => {
      mutationObserver.disconnect()
      resizeObserver.disconnect()
      root.removeEventListener('scroll', handleScroll, { capture: true })
      root.removeEventListener('animationend', handleMotionEnd)
      root.removeEventListener('transitionend', handleMotionEnd)
      tracked.forEach(element => {
        element.removeAttribute('data-overflow-top')
        element.removeAttribute('data-overflow-bottom')
        element.style.removeProperty(FADE_TOP_PROPERTY)
        element.style.removeProperty(FADE_BOTTOM_PROPERTY)
      })
    }
  }, [rootRef])
}
