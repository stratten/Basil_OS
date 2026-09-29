import { useRef, useState, type ReactNode } from 'react'

import { useScrollEdgeFades } from '@/components/motion/useScrollEdgeFades'
import type { SetupStage } from '@/state/setupAssistantStore'

import { SetupStepActionsSlotProvider } from './SetupStepActions'
import { SetupWindowChrome } from './SetupWindowChrome'

interface Props {
  setupStage: SetupStage
  hasActiveArtifact: boolean
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
  onSkip,
  children,
}: Props) {
  const isWrappedUp = setupStage === 'wrap_up'
  const showsProgress = setupStage !== 'welcome'
  const currentPhaseIndex = getCurrentPhaseIndex(setupStage)
  const [stepActionsSlot, setStepActionsSlot] = useState<HTMLDivElement | null>(null)
  const shellRef = useRef<HTMLElement>(null)
  useScrollEdgeFades(shellRef)

  return (
    <SetupWindowChrome title="Basil Setup Assistant">
      <main ref={shellRef} className={`setup-shell ${hasActiveArtifact ? 'with-artifact' : ''}`}>
        <section className="setup-main">
          <header className={`setup-header ${showsProgress ? 'setup-header--with-progress' : ''}`.trim()}>
            {showsProgress && (
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
            {!isWrappedUp && (
              <button
                type="button"
                className="setup-skip-button"
                onClick={onSkip}
                aria-label="Skip setup for now and come back later"
              >
                Skip for now
              </button>
            )}
          </header>

          <section className="setup-card">
            <SetupStepActionsSlotProvider value={stepActionsSlot}>{children}</SetupStepActionsSlotProvider>
          </section>

          <footer className="setup-navigation">
            <div ref={setStepActionsSlot} className="setup-navigation-step" />
          </footer>
        </section>
      </main>
    </SetupWindowChrome>
  )
}
