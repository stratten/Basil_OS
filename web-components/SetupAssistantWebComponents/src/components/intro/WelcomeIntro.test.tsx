// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { WelcomeIntro } from './WelcomeIntro'

let container: HTMLElement
let root: Root

const onChooseManual = vi.fn()
const onChooseSelf = vi.fn()
const onChooseYolo = vi.fn()

function renderWelcome() {
  act(() => {
    root.render(<WelcomeIntro onChooseManual={onChooseManual} onChooseSelf={onChooseSelf} onChooseYolo={onChooseYolo} />)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  onChooseManual.mockReset()
  onChooseSelf.mockReset()
  onChooseYolo.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('WelcomeIntro', () => {
  it('describes the real structure instead of promising a few minutes or counting steps', () => {
    renderWelcome()

    const text = container.textContent ?? ''
    expect(text).toContain('preference steps')
    expect(text).toContain('optional guided conversation')
    expect(text).toContain('Going step by step is what I recommend')
    expect(text).not.toContain('few minutes')
    expect(text).not.toContain('three short')
  })

  it('says what stays on this Mac, where it lives, and where cloud requests go', () => {
    renderWelcome()

    const note = container.querySelector('.welcome-intro-privacy')!
    expect(note.textContent).toContain('What stays on this Mac')
    expect(note.querySelector('code')!.textContent).toBe('.basil')
    expect(note.textContent).toContain('cloud model')
    expect(note.textContent).toContain('go to that provider')
    expect(note.textContent).toContain('Uninstall Basil')
  })

  it('shows the privacy note before the choice so it is read first', () => {
    renderWelcome()

    const note = container.querySelector('.welcome-intro-privacy')!
    const chooser = container.querySelector('.setup-path')!
    expect(note.compareDocumentPosition(chooser) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('hands the manual choice to the app when Continue is pressed', () => {
    renderWelcome()

    act(() => { container.querySelector<HTMLButtonElement>('.welcome-intro-primary')!.click() })

    expect(onChooseManual).toHaveBeenCalledTimes(1)
  })
})
