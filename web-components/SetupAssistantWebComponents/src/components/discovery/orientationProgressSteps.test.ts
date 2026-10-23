import { describe, expect, it } from 'vitest'

import { deriveOrientationProgress, type OrientationProgressInput } from './orientationProgressSteps'

function input(overrides: Partial<OrientationProgressInput> = {}): OrientationProgressInput {
  return {
    isDiscoveryFetching: false,
    isAgentStreaming: false,
    isReady: false,
    observationCount: 0,
    latestProgressNarration: null,
    firstObservationAt: null,
    ...overrides,
  }
}

function states(progressInput: OrientationProgressInput) {
  return deriveOrientationProgress(progressInput).steps.map(step => step.state)
}

describe('deriveOrientationProgress', () => {
  it('starts on the discovery sweep with a fixed, truthful status line', () => {
    const progress = deriveOrientationProgress(input({ isDiscoveryFetching: true }))

    expect(progress.steps.map(step => step.state)).toEqual(['active', 'pending', 'pending', 'pending'])
    expect(progress.statusLine).toBe('Checking your apps, models, email, and connections.')
  })

  it('moves to reading how you work once discovery settles, using the model narration when present', () => {
    expect(states(input({ isAgentStreaming: true }))).toEqual(['done', 'active', 'pending', 'pending'])
    expect(deriveOrientationProgress(input({ isAgentStreaming: true })).statusLine)
      .toBe('Starting to read through what I found.')

    const narrated = deriveOrientationProgress(input({
      isAgentStreaming: true,
      latestProgressNarration: { message: 'Looking at how you use Mail.', at: 1000 },
    }))
    expect(narrated.statusLine).toBe('Looking at how you use Mail.')
  })

  it('keeps the latest narration no matter how old it is', () => {
    const progress = deriveOrientationProgress(input({
      isAgentStreaming: true,
      latestProgressNarration: { message: 'Reading your profile.', at: 1 },
    }))

    expect(progress.statusLine).toBe('Reading your profile.')
  })

  it('advances on the first observation and ignores narration from before it', () => {
    const progress = deriveOrientationProgress(input({
      isAgentStreaming: true,
      observationCount: 2,
      firstObservationAt: 5000,
      latestProgressNarration: { message: 'Reading your profile.', at: 4000 },
    }))

    expect(progress.steps.map(step => step.state)).toEqual(['done', 'done', 'active', 'pending'])
    expect(progress.steps[2].label).toBe("What's worth bringing up (2)")
    expect(progress.statusLine).toBe('2 things worth bringing up so far.')
  })

  it('shows narration that arrives after the first observation', () => {
    const progress = deriveOrientationProgress(input({
      isAgentStreaming: true,
      observationCount: 1,
      firstObservationAt: 5000,
      latestProgressNarration: { message: 'Checking your connected tools.', at: 6000 },
    }))

    expect(progress.statusLine).toBe('Checking your connected tools.')
  })

  it('uses the singular noun for a single observation', () => {
    const progress = deriveOrientationProgress(input({ isAgentStreaming: true, observationCount: 1, firstObservationAt: 1 }))

    expect(progress.statusLine).toBe('1 thing worth bringing up so far.')
  })

  it('says it is laying out findings once the turn ends but cards are still revealing', () => {
    const progress = deriveOrientationProgress(input({ observationCount: 3, firstObservationAt: 1 }))

    expect(progress.statusLine).toBe('Laying out what I found.')
  })

  it('marks every step done and drops the status line when ready', () => {
    const progress = deriveOrientationProgress(input({ isReady: true, observationCount: 3, firstObservationAt: 1 }))

    expect(progress.steps.map(step => step.state)).toEqual(['done', 'done', 'done', 'done'])
    expect(progress.statusLine).toBeNull()
  })

  it('completes cleanly when the model found nothing worth bringing up', () => {
    const progress = deriveOrientationProgress(input({ isReady: true }))

    expect(progress.steps.map(step => step.state)).toEqual(['done', 'done', 'done', 'done'])
    expect(progress.steps[2].label).toBe("What's worth bringing up")
  })
})
