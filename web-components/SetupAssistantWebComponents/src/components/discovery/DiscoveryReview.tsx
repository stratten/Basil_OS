import { useEffect, useMemo, useState } from 'react'

import type { SetupDiscoveryFact } from '@/types'

interface Props {
  facts: SetupDiscoveryFact[]
}

interface DiscoveryObservation {
  id: string
  label: string
  title: string
  detail: string
  tone: 'email' | 'profile' | 'privacy' | 'tools' | 'ready'
}

function formatNames(names: string[]): string {
  const uniqueNames = Array.from(new Set(names.filter(Boolean)))
  if (uniqueNames.length === 0) {
    return ''
  }
  if (uniqueNames.length === 1) {
    return uniqueNames[0]
  }
  if (uniqueNames.length === 2) {
    return `${uniqueNames[0]} and ${uniqueNames[1]}`
  }
  return `${uniqueNames.slice(0, -1).join(', ')}, and ${uniqueNames[uniqueNames.length - 1]}`
}

function buildDiscoveryObservations(facts: SetupDiscoveryFact[]): DiscoveryObservation[] {
  const observations: DiscoveryObservation[] = []
  const emailClientFacts = facts.filter(fact => fact.source === 'email_clients')
  const primaryEmailClient = emailClientFacts.find(fact => fact.metadata.is_primary === 'true')
  const emailClientNames = formatNames([
    primaryEmailClient?.value ?? '',
    ...emailClientFacts.filter(fact => fact !== primaryEmailClient).map(fact => fact.value),
  ])
  const profileFactCount = facts.filter(fact => fact.source === 'user_profile').length
  const localModelFacts = facts.filter(fact => (
    fact.source === 'model_status'
    && (
      fact.metadata.location === 'local'
      || fact.metadata.recommended_for_onboarding === 'true'
      || fact.id.startsWith('model-catalog-')
    )
  ))
  const connectionFacts = facts.filter(fact => fact.source === 'connections')
  const connectedToolFacts = connectionFacts.filter(fact => fact.metadata.auth_status === 'connected')
  const availableToolFacts = connectionFacts.filter(fact => fact.metadata.auth_status !== 'connected')
  const connectedToolNames = formatNames(connectedToolFacts.map(fact => fact.metadata.friendly_name || fact.value))
  const availableToolNames = formatNames(availableToolFacts.map(fact => fact.metadata.friendly_name || fact.value))

  if (emailClientNames) {
    observations.push({
      id: 'email-context',
      label: 'Email',
      title: `${emailClientNames} ${emailClientNames.includes(' and ') ? 'look' : 'looks'} available.`,
      detail: 'If email help becomes useful, I can suggest it without asking you to explain which app you use first.',
      tone: 'email',
    })
  }

  if (profileFactCount > 0) {
    observations.push({
      id: 'profile-context',
      label: 'Profile',
      title: 'Some profile basics are already filled in.',
      detail: 'That should let me ask fewer setup questions and focus on reviewing anything that looks incomplete.',
      tone: 'profile',
    })
  }

  if (localModelFacts.length > 0) {
    observations.push({
      id: 'model-context',
      label: 'Privacy',
      title: 'Local/private model options are available.',
      detail: 'I can keep those choices in mind when suggesting what to prepare next.',
      tone: 'privacy',
    })
  }

  if (connectionFacts.length > 0) {
    observations.push({
      id: 'connection-context',
      label: 'Work tools',
      title: connectedToolNames
        ? `${connectedToolNames} ${connectedToolNames.includes(' and ') ? 'look' : 'looks'} connected.`
        : `${availableToolNames || 'A few supported tools'} can be connected later if useful.`,
      detail: connectedToolNames
        ? (
          availableToolNames
            ? `${availableToolNames} can stay optional. I'll still ask before using or changing anything.`
            : "I'll still ask before using or changing anything."
        )
        : 'You can skip them, defer them, or approve them one at a time.',
      tone: 'tools',
    })
  }

  return observations.slice(0, 4)
}

export function DiscoveryReview({ facts }: Props) {
  const observations = useMemo(() => buildDiscoveryObservations(facts), [facts])
  const [visibleObservationCount, setVisibleObservationCount] = useState(0)
  const visibleObservations = observations.slice(0, visibleObservationCount)
  const isOrienting = observations.length > 0 && visibleObservationCount < observations.length

  useEffect(() => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion || observations.length === 0) {
      setVisibleObservationCount(observations.length)
      return undefined
    }

    setVisibleObservationCount(0)
    const timers = observations.map((_, index) => (
      window.setTimeout(() => {
        setVisibleObservationCount(currentCount => Math.max(currentCount, index + 1))
      }, 220 + index * 780)
    ))

    return () => {
      timers.forEach(timer => window.clearTimeout(timer))
    }
  }, [observations])

  return (
    <div className="phase-section">
      <div className="discovery-intro">
        <p className="eyebrow">Getting oriented</p>
        <h2>I have enough context to suggest a setup path.</h2>
        <p>
          Here are the useful signals I noticed. The detailed checks stay in the background;
          the next screen will turn this into choices you can approve, skip, or defer.
        </p>
      </div>

      {observations.length > 0 ? (
        <>
          <div className="discovery-orientation-status" aria-live="polite">
            {isOrienting ? "I'm getting oriented..." : 'Ready for the next step.'}
          </div>
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
        </>
      ) : (
        <article className="discovery-observation-card tone-ready">
          <div className="discovery-observation-marker" aria-hidden="true" />
          <div>
            <span className="discovery-observation-label">Ready</span>
            <h3>I'm ready to continue.</h3>
            <p>The next screen will focus on reviewable setup choices, not a technical checklist.</p>
          </div>
        </article>
      )}
    </div>
  )
}

