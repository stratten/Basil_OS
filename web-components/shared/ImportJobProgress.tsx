import { useEffect, useRef, useState } from 'react'
import type { ImportStage } from './contextImportClient'
import './context-import-panel.css'

type ImportKind = 'records' | 'profile'

interface Props {
  kind: ImportKind
  phase: 'starting' | 'running'
  message: string
  done: number
  total: number
  stage: ImportStage
  tokensWritten: number
  /** The latest stretch of what the model is writing. Empty when the model does not stream, as with a cloud model. */
  thinking: string
  onCancel: () => void
}

interface StageLabel {
  id: ImportStage
  label: string
}

const PROFILE_STAGES: StageLabel[] = [
  { id: 'loading', label: 'Getting the model ready' },
  { id: 'reading', label: 'Reading your text' },
  { id: 'combining', label: 'Combining what it learned' },
  { id: 'writing', label: 'Writing your profile' },
]

const RECORDS_STAGES: StageLabel[] = [
  { id: 'loading', label: 'Getting the model ready' },
  { id: 'reading', label: 'Reading your text' },
]

/** After this many seconds a quiet reassurance appears, because a large local model can take a minute or more. */
const REASSURE_AFTER_SECONDS = 20
/** English prose runs to about three quarters of a word per token. */
const WORDS_PER_TOKEN = 0.75

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

function approximateWords(tokens: number): number {
  const words = tokens * WORDS_PER_TOKEN
  return words < 100 ? Math.round(words / 10) * 10 : Math.round(words / 50) * 50
}

function stageFraction(stages: StageLabel[], stage: ImportStage, done: number, total: number): number {
  const index = Math.max(stages.findIndex(entry => entry.id === stage), 0)
  const partShare = stage === 'reading' && total > 0 ? Math.min(done / total, 1) : 0
  return (index + partShare) / stages.length
}

/** Real progress from the backend job: the stage it is in, a moving bar, how long it has been working, how much the model has written, and a Cancel button. */
export function ImportJobProgress({ kind, phase, message, done, total, stage, tokensWritten, thinking, onCancel }: Props) {
  const stopping = message === 'Stopping.'
  const stages = kind === 'profile' ? PROFILE_STAGES : RECORDS_STAGES
  const activeIndex = Math.max(stages.findIndex(entry => entry.id === stage), 0)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const thinkingRef = useRef<HTMLDivElement | null>(null)

  // The newest words are at the end, so the panel follows them as they arrive.
  useEffect(() => {
    const panel = thinkingRef.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [thinking])

  useEffect(() => {
    const startedAt = Date.now()
    const timer = window.setInterval(() => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const fraction = Math.max(stageFraction(stages, stage, done, total), 0.04)
  const words = approximateWords(tokensWritten)

  return (
    <div className="context-import-progress" role="status" aria-live="polite" data-testid="context-import-progress">
      <ol className="context-import-stages" aria-label="Import stages">
        {stages.map((entry, index) => {
          const state = index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending'
          return (
            <li key={entry.id} className={`context-import-stage context-import-stage--${state}`} aria-current={state === 'active' ? 'step' : undefined}>
              <span className="context-import-stage-marker" aria-hidden="true" />
              {entry.label}
            </li>
          )
        })}
      </ol>
      <div
        className="context-import-progress-track"
        role="progressbar"
        aria-label="Import progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fraction * 100)}
      >
        <div className="context-import-progress-fill" style={{ width: `${Math.round(fraction * 100)}%` }} />
      </div>
      <p className="context-import-hint">{message}{total > 0 && stage === 'reading' ? ` (${done} of ${total})` : ''}</p>
      <p className="context-import-hint" data-testid="context-import-elapsed">
        {`Working for ${formatElapsed(elapsedSeconds)}.`}
        {tokensWritten > 0 && !thinking ? ` The model has written about ${words} ${words === 1 ? 'word' : 'words'} so far.` : ''}
      </p>
      {thinking ? (
        <div className="context-import-thinking-block">
          <p className="context-import-label" id="context-import-thinking-label">What the model is thinking</p>
          <div ref={thinkingRef} className="context-import-thinking" role="log" tabIndex={0} aria-labelledby="context-import-thinking-label" data-testid="context-import-thinking">
            {thinking}
          </div>
        </div>
      ) : null}
      {elapsedSeconds >= REASSURE_AFTER_SECONDS && !stopping ? (
        <p className="context-import-hint" data-testid="context-import-reassurance">
          Still working. A large model running on your Mac can take a minute or more, and nothing leaves this Mac while it does.
        </p>
      ) : null}
      <div className="context-import-modal-actions">
        <button type="button" className="secondary-button" disabled={phase === 'starting' || stopping} onClick={onCancel}>
          {stopping ? 'Stopping...' : 'Cancel'}
        </button>
      </div>
    </div>
  )
}
