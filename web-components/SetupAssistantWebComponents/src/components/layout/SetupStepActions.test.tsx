// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupStage } from '@/state/setupAssistantStore'

import { SetupShell } from './SetupShell'
import { SetupStepActions } from './SetupStepActions'

let container: HTMLElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.matchMedia = vi.fn().mockReturnValue({ matches: false })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function renderShell(setupStage: SetupStage, onSkip = vi.fn()) {
  act(() => {
    root.render(
      <SetupShell setupStage={setupStage} hasActiveArtifact={false} onSkip={onSkip}>
        <section className="step-content">
          <p>Step body</p>
          <SetupStepActions>
            <button type="button" className="step-continue">Continue</button>
          </SetupStepActions>
        </section>
      </SetupShell>,
    )
  })
  return onSkip
}

describe('SetupStepActions', () => {
  it('renders step actions in the shell footer, not in the card', () => {
    renderShell('intro_and_privacy')

    const footer = container.querySelector('.setup-navigation')!
    expect(Array.from(footer.children).map(child => child.className)).toEqual(['setup-navigation-step'])
    expect(footer.querySelector('.setup-navigation-step .step-continue')).not.toBeNull()
    expect(container.querySelector('.setup-card .step-continue')).toBeNull()
  })

  it('places Skip in the header beside the progress path', () => {
    const onSkip = renderShell('orientation')

    const header = container.querySelector('.setup-header')!
    expect(header.className).toBe('setup-header setup-header--with-progress')
    expect(Array.from(header.children).map(child => child.className)).toEqual(['phase-progress', 'setup-skip-button'])
    expect(container.querySelector('.setup-navigation .setup-skip-button')).toBeNull()

    act(() => { (header.querySelector('.setup-skip-button') as HTMLButtonElement).click() })
    expect(onSkip).toHaveBeenCalledTimes(1)
  })

  it('offers Skip on the welcome screen without the progress path', () => {
    renderShell('welcome')

    const header = container.querySelector('.setup-header')!
    expect(header.className).toBe('setup-header')
    expect(header.querySelector('.phase-progress')).toBeNull()
    expect(header.querySelector('.setup-skip-button')).not.toBeNull()
  })

  it('hides Skip at wrap-up and keeps the step actions in the footer', () => {
    renderShell('wrap_up')

    expect(container.querySelector('.setup-skip-button')).toBeNull()
    expect(container.querySelector('.setup-navigation-step .step-continue')).not.toBeNull()
  })

  it('never renders a shell-level Done or Close button', () => {
    const stages: SetupStage[] = ['welcome', 'intro_and_privacy', 'orientation', 'conversation', 'wrap_up']
    for (const stage of stages) {
      renderShell(stage)
      const labels = Array.from(container.querySelectorAll('button')).map(button => button.textContent ?? '')
      expect(labels.filter(label => /Done|Close/.test(label))).toEqual([])
    }
  })

  it('renders in place when there is no shell footer', () => {
    act(() => {
      root.render(
        <section className="step-content">
          <SetupStepActions>
            <button type="button" className="step-continue">Continue</button>
          </SetupStepActions>
        </section>,
      )
    })

    expect(container.querySelector('.step-content .setup-step-actions .step-continue')).not.toBeNull()
  })
})
