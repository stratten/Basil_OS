// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupStage } from '@/state/setupAssistantStore'

import { StageTransition } from './StageTransition'

let container: HTMLElement
let root: Root
const originalGetAnimations = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'getAnimations')

function setReducedMotion(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches })
}

function render(stage: SetupStage, label: string) {
  act(() => {
    root.render(
      <StageTransition stageKey={stage}>
        <p>{label}</p>
      </StageTransition>,
    )
  })
}

function frame(): HTMLElement {
  return container.querySelector('.setup-stage-frame') as HTMLElement
}

function finishAnimation(animationName: string, target: Element = frame()) {
  const event = new Event('animationend', { bubbles: true })
  Object.defineProperty(event, 'animationName', { value: animationName })
  act(() => { target.dispatchEvent(event) })
}

function mockRunningStageAnimations() {
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', {
    configurable: true,
    writable: true,
    value: function getAnimations(this: HTMLElement) {
      if (this.classList.contains('leaving')) return [{ animationName: 'setupLeaveRise', playState: 'running' }]
      if (this.classList.contains('entering')) return [{ animationName: 'setupEnterRise', playState: 'running' }]
      return []
    },
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
  if (originalGetAnimations) {
    Object.defineProperty(HTMLElement.prototype, 'getAnimations', originalGetAnimations)
  } else {
    delete (HTMLElement.prototype as { getAnimations?: unknown }).getAnimations
  }
})

describe('StageTransition', () => {
  it('settles to idle immediately when no animation is running', () => {
    render('welcome', 'Welcome')
    expect(frame().className).toBe('setup-stage-frame idle')
    expect(frame().textContent).toBe('Welcome')
  })

  it('swaps stages immediately when no animation is running', () => {
    render('welcome', 'Welcome')
    render('intro_and_privacy', 'Intro')
    expect(frame().textContent).toBe('Intro')
    expect(frame().className).toBe('setup-stage-frame idle')
  })

  it('holds the previous stage until its leave animation ends', () => {
    mockRunningStageAnimations()
    render('welcome', 'Welcome')
    expect(frame().className).toBe('setup-stage-frame entering')
    finishAnimation('setupEnterRise')
    expect(frame().className).toBe('setup-stage-frame idle')

    render('intro_and_privacy', 'Intro')
    expect(frame().className).toBe('setup-stage-frame leaving')
    expect(frame().textContent).toBe('Welcome')

    finishAnimation('setupLeaveRise', frame().querySelector('p') as Element)
    expect(frame().textContent).toBe('Welcome')

    finishAnimation('setupLeaveRise')
    expect(frame().textContent).toBe('Intro')
    expect(frame().className).toBe('setup-stage-frame entering')

    finishAnimation('setupEnterRise')
    expect(frame().className).toBe('setup-stage-frame idle')
  })

  it('keeps the outgoing stage content as last rendered, not as first mounted', () => {
    mockRunningStageAnimations()
    render('orientation', 'Reading your setup')
    finishAnimation('setupEnterRise')
    render('orientation', 'Ready to continue')

    render('conversation', 'Conversation')
    expect(frame().className).toBe('setup-stage-frame leaving')
    expect(frame().textContent).toBe('Ready to continue')

    finishAnimation('setupLeaveRise')
    expect(frame().textContent).toBe('Conversation')
  })

  it('skips both phases under reduced motion', () => {
    setReducedMotion(true)
    mockRunningStageAnimations()
    render('welcome', 'Welcome')
    expect(frame().className).toBe('setup-stage-frame idle')
    render('intro_and_privacy', 'Intro')
    expect(frame().textContent).toBe('Intro')
    expect(frame().className).toBe('setup-stage-frame idle')
  })
})
