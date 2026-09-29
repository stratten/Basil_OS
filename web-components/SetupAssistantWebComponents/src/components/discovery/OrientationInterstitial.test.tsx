// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupProgressNarration } from '@/state/setupAssistantStore'
import type { SetupOrientationObservation } from '@/types'

import { OrientationInterstitial } from './OrientationInterstitial'

let container: HTMLElement
let root: Root

interface RenderProps {
  observations?: SetupOrientationObservation[]
  orientationReady?: boolean
  isDiscoveryFetching?: boolean
  isAgentStreaming?: boolean
  latestProgressNarration?: SetupProgressNarration | null
}

function render(props: RenderProps = {}) {
  act(() => {
    root.render(
      <OrientationInterstitial
        observations={props.observations ?? []}
        orientationReady={props.orientationReady ?? false}
        isDiscoveryFetching={props.isDiscoveryFetching ?? false}
        isAgentStreaming={props.isAgentStreaming ?? false}
        latestProgressNarration={props.latestProgressNarration ?? null}
        onReadyForConversation={vi.fn()}
      />,
    )
  })
}

function stepStates(): string[] {
  return Array.from(container.querySelectorAll('.orientation-step')).map(step => (
    ['is-done', 'is-active', 'is-pending'].find(name => step.classList.contains(name)) ?? ''
  ))
}

function statusText(): string | null {
  return container.querySelector('.orientation-footer [role="status"]')?.textContent ?? null
}

const observation: SetupOrientationObservation = {
  id: 'obs-1',
  label: 'Email',
  title: 'Outlook is connected',
  detail: 'Recent threads are available.',
  tone: 'email',
}

beforeEach(() => {
  vi.useFakeTimers()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('OrientationInterstitial progress steps', () => {
  it('renders the four steps with the discovery sweep active', () => {
    render({ isDiscoveryFetching: true })

    expect(Array.from(container.querySelectorAll('.orientation-step-label')).map(label => label.textContent))
      .toEqual(['Your apps and setup', 'How you work', "What's worth bringing up", 'Ready'])
    expect(stepStates()).toEqual(['is-active', 'is-pending', 'is-pending', 'is-pending'])
    expect(container.querySelector('.orientation-step[aria-current="step"]')?.getAttribute('aria-label'))
      .toBe('Your apps and setup: in progress')
    expect(statusText()).toBe('Checking your apps, models, email, and connections.')
  })

  it('keeps the model narration on screen instead of reverting to a canned line', () => {
    render({ isAgentStreaming: true, latestProgressNarration: { message: 'Looking at how you use Mail.', at: Date.now() } })

    act(() => { vi.advanceTimersByTime(20_000) })

    expect(stepStates()).toEqual(['is-done', 'is-active', 'is-pending', 'is-pending'])
    expect(statusText()).toBe('Looking at how you use Mail.')
  })

  it('advances to the observations step and shows the running count', () => {
    render({ isAgentStreaming: true, latestProgressNarration: { message: 'Reading your profile.', at: Date.now() - 1000 } })
    render({
      isAgentStreaming: true,
      observations: [observation],
      latestProgressNarration: { message: 'Reading your profile.', at: Date.now() - 1000 },
    })

    expect(stepStates()).toEqual(['is-done', 'is-done', 'is-active', 'is-pending'])
    expect(container.querySelectorAll('.orientation-step-label')[2].textContent).toBe("What's worth bringing up (1)")
    expect(statusText()).toBe('1 thing worth bringing up so far.')
  })

  it('completes every step and shows the ready note once orientation is ready', () => {
    render({ observations: [observation], orientationReady: true })

    expect(stepStates()).toEqual(['is-done', 'is-done', 'is-done', 'is-done'])
    expect(statusText()).toBeNull()
    expect(container.querySelector('.discovery-ready-note')).not.toBeNull()
  })
})
