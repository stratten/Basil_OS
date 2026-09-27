import { useEffect, useMemo, useRef, useState } from 'react'

import { requestResize } from '@/services/bridge'
import type { SetupProgressNarration } from '@/state/setupAssistantStore'
import type { SetupOrientationObservation } from '@/types'

// Reserve the setup shell, progress, card, navigation, shared frame insets, and 44px React window header outside the orientation section.
const SETUP_SHELL_CHROME_PX = 242

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
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) return undefined
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
  const sectionRef = useRef<HTMLElement | null>(null)
  // Bumps once when the latest narration crosses the freshness boundary so
  // statusSubline re-evaluates and falls back to the canned hint.
  const [, setNarrationStaleTick] = useState(0)

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

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) {
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
  if (phase === 'ready') {
    statusSubline = 'When you\'re ready, let\'s keep going. I\'ll talk through the most useful paths first.'
  } else if (freshNarration) {
    statusSubline = freshNarration
  } else if (phase === 'discovery') {
    statusSubline = discoveryHint
  } else {
    statusSubline = isAgentStreaming ? reasoningHint : 'Reading what landed and pulling the picture together.'
  }

  // Ask the host window to grow as orientation cards land. The Swift seam
  // clamps the requested outer height to its chrome-adjusted window limits,
  // so the renderer only needs to report the desired total height.
  useEffect(() => {
    const section = sectionRef.current
    if (!section || typeof ResizeObserver === 'undefined') {
      return undefined
    }

    let pendingTimer: number | undefined
    const fireResize = () => {
      const desired = section.scrollHeight + SETUP_SHELL_CHROME_PX
      requestResize(Math.ceil(desired))
    }

    const scheduleResize = () => {
      if (pendingTimer !== undefined) {
        window.clearTimeout(pendingTimer)
      }
      pendingTimer = window.setTimeout(() => {
        pendingTimer = undefined
        fireResize()
      }, 120)
    }

    const observer = new ResizeObserver(() => {
      scheduleResize()
    })
    observer.observe(section)

    fireResize()

    return () => {
      observer.disconnect()
      if (pendingTimer !== undefined) {
        window.clearTimeout(pendingTimer)
      }
    }
  }, [])

  useEffect(() => {
    const section = sectionRef.current
    if (!section) {
      return undefined
    }
    if (visibleObservationCount === observations.length && observations.length > 0) {
      const desired = section.scrollHeight + SETUP_SHELL_CHROME_PX
      requestResize(Math.ceil(desired))
    }
    return undefined
  }, [visibleObservationCount, observations.length])

  return (
    <section ref={sectionRef} className="phase-section">
      <div className="discovery-intro">
        <p className="eyebrow">Getting oriented</p>
        <h2>{statusHeadline}</h2>
        <p>
          I'll share what's worth bringing up. You can keep this light, ask for detail, or ask
          me to focus on something specific when we move into the conversation.
        </p>
      </div>

      {visibleObservations.length > 0 && (
        <div className="discovery-observation-list">
          {visibleObservations.map(observation => (
            <article
              key={observation.id}
              className={`discovery-observation-card tone-${observation.tone}`}
            >
              <div className="discovery-observation-marker" aria-hidden="true" />
              <div>
                <span className="discovery-observation-label">{observation.label}</span>
                <h3>{observation.title}</h3>
                <p>{observation.detail}</p>
              </div>
            </article>
          ))}
        </div>
      )}

      {phase !== 'ready' ? (
        <div
          className={`discovery-orientation-status discovery-orientation-status--${phase}`}
          aria-live="polite"
        >
          <span key={statusSubline} className="discovery-orientation-status-text">
            {statusSubline}
          </span>
        </div>
      ) : (
        <p className="quiet-note discovery-ready-note">That's the picture I'm starting with.</p>
      )}

      <div className="button-row button-row--center">
        <button
          type="button"
          className="primary-button"
          onClick={onReadyForConversation}
          disabled={!canContinue}
        >
          Continue with setup
        </button>
      </div>
    </section>
  )
}
