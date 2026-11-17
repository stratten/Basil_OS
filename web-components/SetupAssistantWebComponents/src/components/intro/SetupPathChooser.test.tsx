// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { SetupPathChooser } from './SetupPathChooser'

let container: HTMLElement
let root: Root

const onChooseManual = vi.fn()
const onChooseSelf = vi.fn()
const onChooseYolo = vi.fn()

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  onChooseManual.mockReset()
  onChooseSelf.mockReset()
  onChooseYolo.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(<SetupPathChooser onChooseManual={onChooseManual} onChooseSelf={onChooseSelf} onChooseYolo={onChooseYolo} />)
  })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function radio(name: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="radio"]')).find(button => button.textContent?.includes(name))
  if (!match) throw new Error(`No radio containing "${name}"`)
  return match
}

function click(element: HTMLElement) {
  act(() => { element.click() })
}

function continueButton(): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>('.welcome-intro-primary')!
}

describe('SetupPathChooser', () => {
  it('preselects the step-by-step path and marks it recommended', () => {
    expect(radio('Set it up with me').getAttribute('aria-checked')).toBe('true')
    expect(radio('Set it up for me, my way').getAttribute('aria-checked')).toBe('false')
    expect(radio('Set it all up').getAttribute('aria-checked')).toBe('false')
    expect(radio('Set it up with me').textContent).toContain('Recommended')
    expect(container.textContent?.match(/Recommended/g)).toHaveLength(1)
  })

  it('offers the three paths in a labeled radio group', () => {
    const group = container.querySelector('[role="radiogroup"]')!
    expect(group.getAttribute('aria-label')).toBe('How would you like to set up Basil?')
    expect(container.textContent).toContain('YOLO')
  })

  it('keeps Continue in a footer that is a sibling after the list of paths, so it can stay pinned while the rows scroll', () => {
    const footer = container.querySelector('.setup-path > .setup-path-footer')!
    expect(footer).not.toBeNull()
    expect(footer.previousElementSibling?.classList.contains('setup-path-list')).toBe(true)
    expect(footer.querySelectorAll('button')).toHaveLength(1)
    expect(footer.contains(continueButton())).toBe(true)
    expect(container.querySelector('.setup-path-list')!.contains(continueButton())).toBe(false)
  })

  it('continues with the manual flow by default', () => {
    click(continueButton())

    expect(onChooseManual).toHaveBeenCalledTimes(1)
    expect(onChooseSelf).not.toHaveBeenCalled()
    expect(onChooseYolo).not.toHaveBeenCalled()
  })

  it('shows the comfort levels only for self-setup and starts at Balanced', () => {
    expect(container.textContent).not.toContain('Cautious')

    click(radio('Set it up for me, my way'))

    expect(container.querySelector('[aria-label="How comfortable are you with me doing this?"]')).not.toBeNull()
    expect(radio('Cautious').getAttribute('aria-checked')).toBe('false')
    expect(radio('Balanced').getAttribute('aria-checked')).toBe('true')
    expect(radio('All-in').getAttribute('aria-checked')).toBe('false')
  })

  it('continues self-setup at Balanced when the level is left alone', () => {
    click(radio('Set it up for me, my way'))
    click(continueButton())

    expect(onChooseSelf).toHaveBeenCalledWith('balanced')
  })

  it('marks the chosen row with an empty well, never a tick', () => {
    click(radio('Set it up for me, my way'))

    const indicators = Array.from(container.querySelectorAll('.choice-option-indicator'))
    expect(indicators.length).toBe(6)
    expect(indicators.every(indicator => indicator.textContent === '')).toBe(true)
    expect(container.textContent).not.toContain('✓')
  })

  it('passes the chosen comfort level to self-setup', () => {
    click(radio('Set it up for me, my way'))
    click(radio('Balanced'))
    click(continueButton())

    expect(onChooseSelf).toHaveBeenCalledWith('balanced')
    expect(onChooseManual).not.toHaveBeenCalled()
  })

  it('hides the comfort levels again when another path is chosen, and keeps the level if self-setup returns', () => {
    click(radio('Set it up for me, my way'))
    click(radio('All-in'))
    click(radio('Set it all up'))
    expect(container.textContent).not.toContain('Cautious')

    click(radio('Set it up for me, my way'))
    expect(radio('All-in').getAttribute('aria-checked')).toBe('true')
  })

  it('starts YOLO with no comfort question', () => {
    click(radio('Set it all up'))
    click(continueButton())

    expect(onChooseYolo).toHaveBeenCalledTimes(1)
    expect(onChooseSelf).not.toHaveBeenCalled()
  })
})
