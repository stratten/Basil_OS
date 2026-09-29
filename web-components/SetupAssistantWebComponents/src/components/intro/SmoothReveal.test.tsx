// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { SmoothReveal } from './SmoothReveal'

let container: HTMLElement
let root: Root

function setReducedMotion(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches })
}

function revealNode(): (HTMLElement & { inert?: boolean }) | null {
  return container.querySelector<HTMLElement>('[data-reveal-state]')
}

function finishSizeTransition() {
  const event = new Event('transitionend', { bubbles: true })
  Object.defineProperty(event, 'propertyName', { value: 'grid-template-rows' })
  act(() => { revealNode()!.dispatchEvent(event) })
}

function render(open: boolean, label = 'Revealed content') {
  act(() => {
    root.render(
      <SmoothReveal open={open}>
        <p>{label}</p>
      </SmoothReveal>,
    )
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('SmoothReveal', () => {
  it('renders nothing while closed and expands after mounting when opened', () => {
    setReducedMotion(false)
    render(false)
    expect(revealNode()).toBeNull()

    render(true)
    expect(revealNode()?.dataset.revealState).toBe('open')
    expect(revealNode()?.getAttribute('aria-hidden')).toBe('false')
    expect(revealNode()?.inert).toBe(false)
    expect(revealNode()?.style.transition).toContain('grid-template-rows 400ms cubic-bezier(0.2, 0.8, 0.2, 1)')
    expect(container.textContent).toContain('Revealed content')
  })

  it('keeps the last open content mounted and inert while closing, then unmounts when the size transition ends', () => {
    setReducedMotion(false)
    render(true, 'Key form')
    finishSizeTransition()

    render(false, 'Stale replacement')
    expect(revealNode()?.dataset.revealState).toBe('closed')
    expect(revealNode()?.getAttribute('aria-hidden')).toBe('true')
    expect(revealNode()?.inert).toBe(true)
    expect(container.textContent).toContain('Key form')
    expect(container.textContent).not.toContain('Stale replacement')

    finishSizeTransition()
    expect(revealNode()).toBeNull()
  })

  it('ignores transitions other than the grid-row size change', () => {
    setReducedMotion(false)
    render(true)
    render(false)
    const opacityEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(opacityEnd, 'propertyName', { value: 'opacity' })
    act(() => { revealNode()!.dispatchEvent(opacityEnd) })
    expect(revealNode()).not.toBeNull()
  })

  it('reopens a section that is still closing', () => {
    setReducedMotion(false)
    render(true, 'First')
    render(false, 'First')
    render(true, 'Second')
    expect(revealNode()?.dataset.revealState).toBe('open')
    expect(revealNode()?.inert).toBe(false)
    expect(container.textContent).toContain('Second')
  })

  it('finishes closing when the browser never starts a size transition', () => {
    setReducedMotion(false)
    const prototype = HTMLElement.prototype as HTMLElement & { getAnimations?: () => Animation[] }
    const getAnimations = vi.fn(() => [] as Animation[])
    prototype.getAnimations = getAnimations
    try {
      render(true)
      render(false)
      expect(getAnimations).toHaveBeenCalled()
      expect(revealNode()).toBeNull()
    } finally {
      Reflect.deleteProperty(prototype, 'getAnimations')
    }
  })

  it('waits for a running size transition before unmounting', () => {
    setReducedMotion(false)
    const prototype = HTMLElement.prototype as HTMLElement & { getAnimations?: () => Animation[] }
    prototype.getAnimations = () => [
      { transitionProperty: 'grid-template-rows', playState: 'running' } as unknown as Animation,
    ]
    try {
      render(true)
      render(false)
      expect(revealNode()?.dataset.revealState).toBe('closed')
      finishSizeTransition()
      expect(revealNode()).toBeNull()
    } finally {
      Reflect.deleteProperty(prototype, 'getAnimations')
    }
  })

  it('keeps closing when a reversed opening transition is cancelled and replaced', () => {
    setReducedMotion(false)
    const prototype = HTMLElement.prototype as HTMLElement & { getAnimations?: () => Animation[] }
    let running = true
    prototype.getAnimations = () => (running
      ? [{ transitionProperty: 'grid-template-rows', playState: 'running' } as unknown as Animation]
      : [])
    const cancelSizeTransition = () => {
      const event = new Event('transitioncancel')
      Object.defineProperty(event, 'propertyName', { value: 'grid-template-rows' })
      act(() => { revealNode()!.dispatchEvent(event) })
    }
    try {
      render(true)
      render(false)
      cancelSizeTransition()
      expect(revealNode()?.dataset.revealState).toBe('closed')

      running = false
      cancelSizeTransition()
      expect(revealNode()).toBeNull()
    } finally {
      Reflect.deleteProperty(prototype, 'getAnimations')
    }
  })

  it('switches instantly without transitions under reduced motion', () => {
    setReducedMotion(true)
    render(true)
    expect(revealNode()?.style.transition).toBe('none')

    render(false)
    expect(revealNode()).toBeNull()
  })
})
