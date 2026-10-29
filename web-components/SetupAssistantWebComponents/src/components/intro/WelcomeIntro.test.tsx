// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { WelcomeIntro } from './WelcomeIntro'

let container: HTMLElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('WelcomeIntro', () => {
  it('describes the real structure instead of promising a few minutes', () => {
    const onContinue = vi.fn()
    act(() => { root.render(<WelcomeIntro onContinue={onContinue} />) })

    const text = container.textContent ?? ''
    expect(text).toContain('three short preference steps')
    expect(text).toContain('optional guided conversation')
    expect(text).toContain('stop it any time')
    expect(text).not.toContain('few minutes')

    act(() => { container.querySelector<HTMLButtonElement>('.welcome-intro-primary')!.click() })
    expect(onContinue).toHaveBeenCalledTimes(1)
  })

  it('says what stays on this Mac, where it lives, and where cloud requests go', () => {
    act(() => { root.render(<WelcomeIntro onContinue={vi.fn()} />) })

    const note = container.querySelector('.welcome-intro-privacy')!
    expect(note.textContent).toContain('What stays on this Mac')
    expect(note.querySelector('code')!.textContent).toBe('.basil')
    expect(note.textContent).toContain('cloud model')
    expect(note.textContent).toContain('go to that provider')
    expect(note.textContent).toContain('Uninstall Basil')
  })
})
