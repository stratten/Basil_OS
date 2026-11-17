// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupStage } from '@/state/setupAssistantStore'

import { SetupShell } from './SetupShell'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('SetupShell and the express stage', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    window.webkit = { messageHandlers: { setupAssistant: { postMessage: vi.fn() } } }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  function render(stage: SetupStage) {
    act(() => {
      root.render(
        <SetupShell setupStage={stage} hasActiveArtifact={false} onSkip={() => {}}>
          <div />
        </SetupShell>,
      )
    })
  }

  it('shows the express stage under Setup Preferences, the same pill as the manual steps', () => {
    render('express')

    const active = container.querySelector('.phase-pill.active')!
    expect(active.textContent).toContain('Setup Preferences')
    expect(container.querySelector('.phase-pill.complete')).toBeNull()
  })

  it('shows the progress pills on the express stage, unlike the welcome screen', () => {
    render('welcome')
    expect(container.querySelector('.phase-progress')).toBeNull()

    render('express')
    expect(container.querySelector('.phase-progress')).not.toBeNull()
  })

  it('still offers Skip setup for now during the express stage, and says it leaves the whole setup', () => {
    render('express')

    const skip = container.querySelector('.setup-skip-button')!
    expect(skip.textContent).toBe('Skip setup for now')
    expect(skip.getAttribute('title')).toContain('whole setup')
  })
})
