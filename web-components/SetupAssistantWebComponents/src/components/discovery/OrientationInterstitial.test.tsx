// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupImportedContextSummary, SetupProgressNarration } from '@/state/setupAssistantStore'
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
  importedContext?: SetupImportedContextSummary | null
  onReadyForConversation?: () => void
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
        importedContext={props.importedContext ?? null}
        onReadyForConversation={props.onReadyForConversation ?? vi.fn()}
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

describe('OrientationInterstitial with imported context', () => {
  const imported: SetupImportedContextSummary = {
    entries_added: 0,
    facts_proposed: 0,
    fact_titles: [],
    note_titles: [],
    profile_updated: true,
    profile_summary: 'You are a designer in Boston.',
  }
  const continueButton = () => Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent === 'Continue with setup')!

  it('leads with a card about what the person imported and lets them continue before the sweep finishes', () => {
    const onReadyForConversation = vi.fn()
    render({ importedContext: imported, isDiscoveryFetching: true, onReadyForConversation })

    const card = container.querySelector('[data-testid="orientation-imported-context"]')!
    expect(card.textContent).toContain('From what you imported')
    expect(card.textContent).toContain('Your profile is already in place')
    expect(card.textContent).toContain('You are a designer in Boston.')
    expect(container.querySelector('[data-testid="orientation-skip-note"]')!.textContent).toContain('you can continue now')
    expect(continueButton().disabled).toBe(false)

    act(() => { continueButton().click() })
    expect(onReadyForConversation).toHaveBeenCalledTimes(1)
  })

  it('puts the imported card before the observations and drops the skip note once the step is ready', () => {
    render({ importedContext: imported, observations: [observation], orientationReady: true })

    const titles = Array.from(container.querySelectorAll('.discovery-observation-card h3')).map(heading => heading.textContent)
    expect(titles).toEqual(['Your profile is already in place', 'Outlook is connected'])
    expect(container.querySelector('[data-testid="orientation-skip-note"]')).toBeNull()
  })

  it('keeps waiting for the sweep, with no card and a disabled Continue, when nothing was imported', () => {
    render({ isDiscoveryFetching: true })
    expect(container.querySelector('[data-testid="orientation-imported-context"]')).toBeNull()
    expect(continueButton().disabled).toBe(true)

    render({ importedContext: { ...imported, profile_updated: false, profile_summary: undefined }, isDiscoveryFetching: true })
    expect(container.querySelector('[data-testid="orientation-imported-context"]')).toBeNull()
    expect(continueButton().disabled).toBe(true)
  })

  it('keeps the orientation steps honest while continuing is allowed early', () => {
    render({ importedContext: imported, isDiscoveryFetching: true })

    expect(stepStates()).toEqual(['is-active', 'is-pending', 'is-pending', 'is-pending'])
  })
})
