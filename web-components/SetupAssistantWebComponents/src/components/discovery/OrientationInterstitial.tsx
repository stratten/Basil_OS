import { useEffect, useMemo, useRef, useState } from 'react'

import { SmoothReveal } from '@/components/intro/SmoothReveal'
import { SetupStepActions } from '@/components/layout/SetupStepActions'
import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'
import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import { useStickToBottom } from '@shared/useStickToBottom'
import type { SetupImportedContextSummary, SetupProgressNarration } from '@/state/setupAssistantStore'
import type { SetupOrientationObservation } from '@/types'

import { describeImportedContext } from './importedContextCard'
import { deriveOrientationProgress } from './orientationProgressSteps'
import { plainMarkdownText } from '@shared/plainMarkdownText'

interface Props {
  observations: SetupOrientationObservation[]
  orientationReady: boolean
  isDiscoveryFetching: boolean
  isAgentStreaming: boolean
  latestProgressNarration: SetupProgressNarration | null
  /** Background the person already imported. When there is some, it leads the step and they can continue without waiting for the rest. */
  importedContext?: SetupImportedContextSummary | null
  onReadyForConversation: () => void
}

export function OrientationInterstitial({
  observations,
  orientationReady,
  isDiscoveryFetching,
  isAgentStreaming,
  latestProgressNarration,
  importedContext = null,
  onReadyForConversation,
}: Props) {
  const [visibleObservationCount, setVisibleObservationCount] = useState(0)
  const visibleObservations = observations.slice(0, visibleObservationCount)
  const scrollRegionRef = useRef<HTMLDivElement>(null)
  const observationListRef = useRef<HTMLDivElement>(null)
  const [firstObservationAt, setFirstObservationAt] = useState<number | null>(null)

  useEffect(() => {
    if (observations.length > 0 && firstObservationAt === null) setFirstObservationAt(Date.now())
  }, [observations.length, firstObservationAt])

  useStickToBottom(scrollRegionRef, observationListRef)

  // Phase derivation. Goes from discovery -> reasoning -> ready.
  const phase: 'discovery' | 'reasoning' | 'ready' = useMemo(() => {
    if (isDiscoveryFetching) return 'discovery'
    if (orientationReady && visibleObservationCount >= observations.length) return 'ready'
    return 'reasoning'
  }, [isDiscoveryFetching, orientationReady, visibleObservationCount, observations.length])

  const importedCard = describeImportedContext(importedContext)
  const isReady = phase === 'ready'
  // Someone who already told Basil about themselves is not made to wait for the survey of their setup.
  const canContinue = isReady || importedCard !== null
  const progress = deriveOrientationProgress({
    isDiscoveryFetching,
    isAgentStreaming,
    isReady,
    observationCount: observations.length,
    latestProgressNarration,
    firstObservationAt,
  })

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
          {importedCard && (
            <article className="discovery-observation-card tone-profile" data-testid="orientation-imported-context">
              <div className="discovery-observation-marker" aria-hidden="true" />
              <div>
                <span className="discovery-observation-label">{importedCard.label}</span>
                <h3>{importedCard.title}</h3>
                <p>{importedCard.detail}</p>
              </div>
            </article>
          )}
          {visibleObservations.map(observation => (
            <SmoothReveal key={observation.id} open appear>
              <article className={`discovery-observation-card tone-${observation.tone}`}>
                <div className="discovery-observation-marker" aria-hidden="true" />
                <div>
                  <span className="discovery-observation-label">{observation.label}</span>
                  <h3>{plainMarkdownText(observation.title)}</h3>
                  <p>{plainMarkdownText(observation.detail)}</p>
                </div>
              </article>
            </SmoothReveal>
          ))}
        </div>
      </div>

      <div className="orientation-footer">
        <ol className="orientation-steps" aria-label="Orientation progress">
          {progress.steps.map(step => (
            <li
              key={step.id}
              className={`orientation-step is-${step.state}`}
              aria-current={step.state === 'active' ? 'step' : undefined}
              aria-label={`${step.label}: ${step.state === 'done' ? 'done' : step.state === 'active' ? 'in progress' : 'not started'}`}
            >
              <span className="orientation-step-marker" aria-hidden="true" />
              <span className="orientation-step-label">{step.label}</span>
            </li>
          ))}
        </ol>
        {progress.statusLine ? (
          <>
            <SetupWorkingIndicator label={progress.statusLine} quiet />
            {importedCard && (
              <p className="quiet-note" data-testid="orientation-skip-note">
                You have already told me about yourself, so you can continue now and skip the rest of this. I will start from what you imported.
              </p>
            )}
          </>
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
