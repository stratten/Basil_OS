import { useState } from 'react'

import type { ComfortLevel } from '@/components/express/expressTypes'

export type SetupPath = 'manual' | 'self' | 'yolo'

interface Props {
  onChooseManual: () => void
  onChooseSelf: (comfort: ComfortLevel) => void
  onChooseYolo: () => void
}

interface PathOption {
  id: SetupPath
  title: string
  detail: string
  recommended?: boolean
}

interface ComfortOption {
  id: ComfortLevel
  title: string
  detail: string
}

const PATH_OPTIONS: readonly PathOption[] = [
  {
    id: 'manual',
    title: 'Set it up with me',
    detail: 'A few short steps where you decide each thing, and see what each choice means before you make it.',
    recommended: true,
  },
  {
    id: 'self',
    title: 'Set it up for me, my way',
    detail: 'Tell me how comfortable you are and I will do the setup for you, based on this Mac.',
  },
  {
    id: 'yolo',
    title: 'Set it all up (YOLO)',
    detail: 'Turn on everything useful and download what this Mac can run. You see the full list first and can untick anything.',
  },
]

const COMFORT_OPTIONS: readonly ComfortOption[] = [
  {
    id: 'cautious',
    title: 'Cautious',
    detail: 'Only things that stay on this Mac and need no new macOS permission.',
  },
  {
    id: 'balanced',
    title: 'Balanced',
    detail: 'Also adds Activity Capture and Meeting and Call Detection to the Basil menu, switched on but not started for you.',
  },
  {
    id: 'all_in',
    title: 'All-in',
    detail: 'Also starts capture, meeting detection and the Voice Listener every time Basil launches.',
  },
]

/** The first choice in setup: do it step by step (recommended), let me do it at a chosen comfort level, or do everything. */
export function SetupPathChooser({ onChooseManual, onChooseSelf, onChooseYolo }: Props) {
  const [path, setPath] = useState<SetupPath>('manual')
  const [comfort, setComfort] = useState<ComfortLevel>('balanced')

  const handleContinue = () => {
    if (path === 'manual') onChooseManual()
    else if (path === 'self') onChooseSelf(comfort)
    else onChooseYolo()
  }

  return (
    <div className="setup-path">
      <div className="choice-list setup-path-list" role="radiogroup" aria-label="How would you like to set up Basil?">
        {PATH_OPTIONS.map(option => {
          const selected = path === option.id
          return (
            <div key={option.id} className="choice-option-wrapper">
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                className={['choice-option', 'setup-path-option', selected ? 'selected' : ''].join(' ').trim()}
                onClick={() => setPath(option.id)}
              >
                <div>
                  <strong>
                    {option.title}
                    {option.recommended && <span className="setup-path-badge">Recommended</span>}
                  </strong>
                  <span>{option.detail}</span>
                </div>
                <span className="choice-option-indicator" aria-hidden="true" />
              </button>
              {option.id === 'self' && selected && (
                <div className="setup-path-comfort" role="radiogroup" aria-label="How comfortable are you with me doing this?">
                  {COMFORT_OPTIONS.map(level => {
                    const levelSelected = comfort === level.id
                    return (
                      <button
                        key={level.id}
                        type="button"
                        role="radio"
                        aria-checked={levelSelected}
                        className={['choice-option', 'setup-path-comfort-option', levelSelected ? 'selected' : ''].join(' ').trim()}
                        onClick={() => setComfort(level.id)}
                      >
                        <div>
                          <strong>{level.title}</strong>
                          <span>{level.detail}</span>
                        </div>
                        <span className="choice-option-indicator" aria-hidden="true" />
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <button type="button" className="primary-button welcome-intro-primary" onClick={handleContinue}>
        Continue
      </button>
    </div>
  )
}
