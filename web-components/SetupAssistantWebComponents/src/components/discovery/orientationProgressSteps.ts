import type { SetupProgressNarration } from '@/state/setupAssistantStore'

export type OrientationStepId = 'setup' | 'how_you_work' | 'worth_bringing_up' | 'ready'
export type OrientationStepState = 'done' | 'active' | 'pending'

export interface OrientationStep {
  id: OrientationStepId
  label: string
  state: OrientationStepState
}

export interface OrientationProgressInput {
  isDiscoveryFetching: boolean
  isAgentStreaming: boolean
  isReady: boolean
  observationCount: number
  latestProgressNarration: SetupProgressNarration | null
  firstObservationAt: number | null
}

export interface OrientationProgress {
  steps: OrientationStep[]
  statusLine: string | null
}

// Every step boundary is a real event: the discovery requests settling, the first observation landing, and the orientation turn settling with every card revealed.
function activeStepIndex(input: OrientationProgressInput): number {
  if (input.isReady) return 4
  if (input.isDiscoveryFetching) return 0
  if (input.observationCount === 0) return 1
  return 2
}

function narrationSince(
  narration: SetupProgressNarration | null,
  since: number | null,
): string | null {
  if (!narration) return null
  if (since !== null && narration.at < since) return null
  return narration.message
}

function statusLineFor(activeIndex: number, input: OrientationProgressInput): string | null {
  if (activeIndex === 0) return 'Checking your apps, models, email, and connections.'
  if (activeIndex === 1) {
    return narrationSince(input.latestProgressNarration, null)
      ?? 'Starting to read through what I found.'
  }
  if (activeIndex === 2) {
    if (!input.isAgentStreaming) return 'Laying out what I found.'
    const noun = input.observationCount === 1 ? 'thing' : 'things'
    return narrationSince(input.latestProgressNarration, input.firstObservationAt)
      ?? `${input.observationCount} ${noun} worth bringing up so far.`
  }
  return null
}

export function deriveOrientationProgress(input: OrientationProgressInput): OrientationProgress {
  const activeIndex = activeStepIndex(input)
  const labels: Array<[OrientationStepId, string]> = [
    ['setup', 'Your apps and setup'],
    ['how_you_work', 'How you work'],
    [
      'worth_bringing_up',
      input.observationCount > 0
        ? `What's worth bringing up (${input.observationCount})`
        : "What's worth bringing up",
    ],
    ['ready', 'Ready'],
  ]
  const steps = labels.map(([id, label], index): OrientationStep => ({
    id,
    label,
    state: index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending',
  }))
  return { steps, statusLine: statusLineFor(activeIndex, input) }
}
