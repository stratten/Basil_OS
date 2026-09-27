import type { ReactNode } from 'react'

import type { SetupStage } from '@/state/setupAssistantStore'

import { SetupWindowChrome } from './SetupWindowChrome'

interface Props {
  setupStage: SetupStage
  hasActiveArtifact: boolean
  onFinish: () => void
  onSkip: () => void
  children: ReactNode
}

interface SetupPhasePathItem {
  id: string
  label: string
  stages: readonly SetupStage[]
}

const setupPhasePath: readonly SetupPhasePathItem[] = [
  {
    id: 'setup_preferences',
    label: 'Setup Preferences',
    stages: ['intro_and_privacy'],
  },
  {
    id: 'getting_oriented',
    label: 'Getting Oriented',
    stages: ['orientation'],
  },
  {
    id: 'working_together',
    label: 'Working Together',
    stages: ['conversation'],
  },
  {
    id: 'wrap_up',
    label: 'Wrap-Up',
    stages: ['wrap_up'],
  },
] as const

function getCurrentPhaseIndex(setupStage: SetupStage): number {
  if (setupStage === 'welcome') return -1
  return setupPhasePath.findIndex(phase => phase.stages.includes(setupStage))
}

export function SetupShell({
  setupStage,
  hasActiveArtifact,
  onFinish,
  onSkip,
  children,
}: Props) {
  const isWrappedUp = setupStage === 'wrap_up'
  const currentPhaseIndex = getCurrentPhaseIndex(setupStage)

  return (
    <SetupWindowChrome title="Basil Setup Assistant">
      <main className={`setup-shell ${hasActiveArtifact ? 'with-artifact' : ''}`}>
        <section className="setup-main">
          {setupStage !== 'welcome' && (
            <nav className="phase-progress" aria-label="Setup progress">
              {setupPhasePath.map((phase, index) => {
                const isActive = index === currentPhaseIndex
                const isComplete = index < currentPhaseIndex
                const stateClass = isActive ? 'active' : isComplete ? 'complete' : 'upcoming'
                return (
                  <div
                    key={phase.id}
                    className={`phase-pill ${stateClass}`}
                    aria-current={isActive ? 'step' : undefined}
                  >
                    <span>{isComplete || (isWrappedUp && isActive) ? '✓' : index + 1}</span>
                    {phase.label}
                  </div>
                )
              })}
            </nav>
          )}

          <section className="setup-card">{children}</section>

          <footer className="setup-navigation">
            {!isWrappedUp && (
              <button
                type="button"
                className="setup-skip-button"
                onClick={onSkip}
                aria-label="Skip setup for now and come back later"
              >
                Skip setup for now
              </button>
            )}
            <button type="button" className="secondary-button" onClick={onFinish}>
              {isWrappedUp ? 'Close' : 'Done with setup'}
            </button>
          </footer>
        </section>
      </main>
    </SetupWindowChrome>
  )
}
