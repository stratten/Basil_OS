import { useEffect, useMemo, useRef, useState } from 'react'

import { SmoothReveal } from '@/components/intro/SmoothReveal'
import { SetupStepActions } from '@/components/layout/SetupStepActions'
import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'
import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import { useStickToBottom } from '@/components/motion/useStickToBottom'
import type { SetupProgressNarration } from '@/state/setupAssistantStore'
import type { SetupOrientationObservation } from '@/types'

interface Props {
  observations: SetupOrientationObservation[]
  orientationReady: boolean
  isDiscoveryFetching: boolean
  isAgentStreaming: boolean
  latestProgressNarration: SetupProgressNarration | null
  onReadyForConversation: () => void
}

const DISCOVERY_HINT_LINES = [
  'Taking a look at the apps you have open and installed.',
  'Reading what I already know about how you work.',
  'Checking what tools are wired up and what is still untouched.',
  'Looking at how you already use your machine day to day.',
  'Comparing what is open right now with what you usually run.',
  'Skimming recent activity to see how your day shapes up.',
]

const REASONING_HINT_LINES = [
  'Forming a first picture of what could be most useful to you.',
  'Looking for one or two things that would help right away.',
  'Thinking through what is worth bringing up first.',
  'Weighing which capabilities matter most given what I see.',
  'Sketching where I would start if you wanted to dive in.',
]

const NARRATION_FRESHNESS_MS = 6000

function useRotatingHint(lines: string[], intervalMs = 2200, active = true) {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (!active || lines.length <= 1) return undefined
    if (prefersReducedMotion()) return undefined
    const timer = window.setInterval(() => {
      setIndex(current => (current + 1) % lines.length)
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [active, intervalMs, lines.length])

  return lines[index] ?? lines[0] ?? ''
}

export function OrientationInterstitial({
  observations,
  orientationReady,
  isDiscoveryFetching,
  isAgentStreaming,
  latestProgressNarration,
  onReadyForConversation,
}: Props) {
  const [visibleObservationCount, setVisibleObservationCount] = useState(0)
  const visibleObservations = observations.slice(0, visibleObservationCount)
  const scrollRegionRef = useRef<HTMLDivElement>(null)
  const observationListRef = useRef<HTMLDivElement>(null)
  // Bumps once when the latest narration crosses the freshness boundary so
  // statusSubline re-evaluates and falls back to the canned hint.
  const [, setNarrationStaleTick] = useState(0)

  useStickToBottom(scrollRegionRef, observationListRef)

  // Phase derivation. Goes from discovery -> reasoning -> ready.
  const phase: 'discovery' | 'reasoning' | 'ready' = useMemo(() => {
    if (isDiscoveryFetching) return 'discovery'
    if (orientationReady && visibleObservationCount >= observations.length) return 'ready'
    return 'reasoning'
  }, [isDiscoveryFetching, orientationReady, visibleObservationCount, observations.length])

  const canContinue = phase === 'ready'
  const discoveryHint = useRotatingHint(DISCOVERY_HINT_LINES, 3000, phase === 'discovery')
  const reasoningHint = useRotatingHint(REASONING_HINT_LINES, 3200, phase === 'reasoning')

  useEffect(() => {
    if (observations.length === 0) {
      setVisibleObservationCount(0)
      return undefined
    }

    if (prefersReducedMotion()) {
      setVisibleObservationCount(observations.length)
      return undefined
    }

    if (visibleObservationCount >= observations.length) {
      return undefined
    }

    const timer = window.setTimeout(() => {
      setVisibleObservationCount(currentCount => Math.min(observations.length, currentCount + 1))
    }, visibleObservationCount === 0 ? 700 : 1500)

    return () => window.clearTimeout(timer)
  }, [observations.length, visibleObservationCount])

  const statusHeadline = phase === 'discovery'
    ? 'Getting a feel for your setup.'
    : phase === 'reasoning'
      ? 'Putting it together now.'
      : 'I\'ve got a first read on your setup.'

  // When a narration arrives, schedule a single re-render at the moment it
  // expires so the subline falls back to the canned hint without leaving a
  // stale model line on screen.
  useEffect(() => {
    if (!latestProgressNarration) return undefined
    const elapsed = Date.now() - latestProgressNarration.at
    const remaining = NARRATION_FRESHNESS_MS - elapsed
    if (remaining <= 0) return undefined
    const timer = window.setTimeout(() => {
      setNarrationStaleTick(tick => tick + 1)
    }, remaining + 16)
    return () => window.clearTimeout(timer)
  }, [latestProgressNarration])

  const freshNarration = useMemo(() => {
    if (!latestProgressNarration) return null
    if (Date.now() - latestProgressNarration.at > NARRATION_FRESHNESS_MS) return null
    return latestProgressNarration.message
  }, [latestProgressNarration])

  let statusSubline: string
  if (freshNarration) {
    statusSubline = freshNarration
  } else if (phase === 'discovery') {
    statusSubline = discoveryHint
  } else {
    statusSubline = isAgentStreaming ? reasoningHint : 'Reading what landed and pulling the picture together.'
  }

  return (
    <section className="phase-section orientation-section">
      <div className="discovery-intro">
        <p className="eyebrow">Getting oriented</p>
        <h2>{statusHeadline}</h2>
        <p>
          I'll share what's worth bringing up. You can keep this light, ask for detail, or ask
          me to focus on something specific when we move into the conversation.
        </p>
      </div>

      <div ref={scrollRegionRef} className="orientation-scroll-region">
        <div ref={observationListRef} className="discovery-observation-list">
          {visibleObservations.map(observation => (
            <SmoothReveal key={observation.id} open appear>
              <article className={`discovery-observation-card tone-${observation.tone}`}>
                <div className="discovery-observation-marker" aria-hidden="true" />
                <div>
                  <span className="discovery-observation-label">{observation.label}</span>
                  <h3>{observation.title}</h3>
                  <p>{observation.detail}</p>
                </div>
              </article>
            </SmoothReveal>
          ))}
        </div>
      </div>

      <div className="orientation-footer">
        {phase !== 'ready' ? (
          <SetupWorkingIndicator label={statusSubline} />
        ) : (
          <p className="quiet-note discovery-ready-note setup-motion-enter">
            That's the picture I'm starting with. When you're ready, let's keep going. I'll talk
            through the most useful paths first.
          </p>
        )}
      </div>

      <SetupStepActions>
        <button
          type="button"
          className="primary-button"
          onClick={onReadyForConversation}
          disabled={!canContinue}
        >
          Continue with setup
        </button>
      </SetupStepActions>
    </section>
  )
}
