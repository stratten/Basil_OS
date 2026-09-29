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

function revealNode(): HTMLElement | null {
  return container.querySelector<HTMLElement>('[data-reveal-state]')
}

function render(open: boolean, appear: boolean) {
  act(() => {
    root.render(
      <SmoothReveal open={open} appear={appear}>
        <p>Card</p>
      </SmoothReveal>,
    )
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  setReducedMotion(false)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SmoothReveal appear', () => {
  it('expands on mount when appear is set', () => {
    render(true, true)
    expect(revealNode()?.dataset.revealState).toBe('open')
  })

  it('renders expanded when mounted open without appear', () => {
    render(true, false)
    expect(revealNode()?.dataset.revealState).toBe('open')
  })

  it('opens a reveal that was mounted closed', () => {
    render(false, false)
    expect(revealNode()).toBeNull()
    render(true, false)
    expect(revealNode()?.dataset.revealState).toBe('open')
  })

  it('opens immediately under reduced motion', () => {
    setReducedMotion(true)
    render(true, true)
    expect(revealNode()?.dataset.revealState).toBe('open')
  })
})
