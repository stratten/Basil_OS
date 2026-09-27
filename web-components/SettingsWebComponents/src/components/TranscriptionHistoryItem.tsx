import { useEffect, useRef, useState } from 'react'
import type { TranscriptionModelOptionFields, TranscriptionRecordFields } from '../types'

interface TranscriptionHistoryItemProps {
  record: TranscriptionRecordFields
  isPlaying: boolean
  isRetranscribing: boolean
  actionPending: boolean
  progressMessage: string | null
  progressFraction: number | null
  availableRetranscriptionModels: TranscriptionModelOptionFields[]
  currentGlobalTranscriptionModelId: string
  onPlay: () => void
  onStop: () => void
  onRetranscribe: (modelId?: string) => void
  onDelete: () => void
}

type HistoryIconKind = 'chevron' | 'copy' | 'copied' | 'delete' | 'eye' | 'play' | 'retry' | 'stop'

function HistoryIcon({ kind }: { kind: HistoryIconKind }) {
  if (kind === 'play') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 10 7-10 7V5Z" /></svg>
  if (kind === 'stop') return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1" /></svg>
  if (kind === 'chevron') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
  if (kind === 'eye') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12s3.2-5 9-5 9 5 9 5-3.2 5-9 5-9-5-9-5Z" /><circle cx="12" cy="12" r="2.5" /></svg>
  if (kind === 'copy') return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="2" /><path d="M5 16V6a2 2 0 0 1 2-2h8" /></svg>
  if (kind === 'copied') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12 2.2 2.2 4.8-5" /></svg>
  if (kind === 'retry') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 8V4l-2.2 2.2A8 8 0 1 0 20 12" /><path d="M19 4v4h-4" /></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg>
}

export function TranscriptionHistoryItem({
  record,
  isPlaying,
  isRetranscribing,
  actionPending,
  progressMessage,
  progressFraction,
  availableRetranscriptionModels,
  currentGlobalTranscriptionModelId,
  onPlay,
  onStop,
  onRetranscribe,
  onDelete,
}: TranscriptionHistoryItemProps) {
  const [showFullText, setShowFullText] = useState(false)
  const [copied, setCopied] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [showRetranscribeMenu, setShowRetranscribeMenu] = useState(false)
  const retranscribeMenuRef = useRef<HTMLDivElement>(null)

  const isFailed = record.status === 'failed'
  const isPending = record.status === 'pending'
  const textActionsDisabled = isFailed || isPending

  function handleCopy() {
    navigator.clipboard.writeText(record.displayText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  function handleDeleteClick() {
    if (confirmingDelete) {
      onDelete()
      setConfirmingDelete(false)
      return
    }
    setConfirmingDelete(true)
  }

  function handleRetranscribeClick(modelId?: string) {
    setShowRetranscribeMenu(false)
    onRetranscribe(modelId)
  }

  useEffect(() => {
    if (!showRetranscribeMenu) return
    function dismissRetranscribeMenu(event: PointerEvent) {
      if (!retranscribeMenuRef.current?.contains(event.target as Node)) setShowRetranscribeMenu(false)
    }
    document.addEventListener('pointerdown', dismissRetranscribeMenu)
    return () => document.removeEventListener('pointerdown', dismissRetranscribeMenu)
  }, [showRetranscribeMenu])

  const localModels = availableRetranscriptionModels.filter((model) => !model.isApiModel)
  const apiModels = availableRetranscriptionModels.filter((model) => model.isApiModel)
  const currentModel = availableRetranscriptionModels.find((model) => model.id === currentGlobalTranscriptionModelId)

  return (
    <div className={`transcription-history-item${isFailed ? ' transcription-history-item-failed' : ''}${isPending ? ' transcription-history-item-pending' : ''}`}>
      <div className="transcription-history-item-header">
        <div>
          <span className="transcription-history-item-date">Recorded {record.formattedDate}</span>
          {record.formattedLastTranscribedDate && (
            <span className="transcription-history-item-last-transcribed">Last transcribed {record.formattedLastTranscribedDate}</span>
          )}
        </div>
        {isFailed && <span className="transcription-history-status-badge transcription-history-status-failed"><HistoryIcon kind="retry" />Failed</span>}
        {isPending && <span className="transcription-history-status-badge transcription-history-status-pending">Transcribing…</span>}
        <span className="transcription-history-item-duration">{record.formattedDuration}</span>
      </div>

      <div className="transcription-history-item-body">
        {isFailed ? (
          <>
            <p className="transcription-history-failed-text">Transcription failed.</p>
            <p className="transcription-settings-hint">{record.errorMessage || 'Audio was saved — use Retry to transcribe again.'}</p>
          </>
        ) : isPending ? (
          <p className="transcription-settings-hint">Transcribing… text will appear here when the model finishes.</p>
        ) : showFullText ? (
          <p className="transcription-history-item-text-full">{record.displayText}</p>
        ) : (
          <p className="transcription-history-item-text-preview">{record.displayText}</p>
        )}
      </div>

      {isRetranscribing && (
        <div className="transcription-history-progress">
          <span>{progressMessage || 'Retranscribing...'}</span>
          {progressFraction != null && (
            <progress className="transcription-history-progress-bar" value={progressFraction} max={1} />
          )}
        </div>
      )}

      <div className="transcription-history-item-actions">
        <button
          type="button"
          className="transcription-history-action transcription-history-play-action"
          disabled={actionPending || (textActionsDisabled && !isPlaying)}
          onClick={() => (isPlaying ? onStop() : onPlay())}
        >
          <HistoryIcon kind={isPlaying ? 'stop' : 'play'} />
          <span>{isPlaying ? 'Stop' : 'Play'}</span>
        </button>
        <button
          type="button"
          className="transcription-history-action"
          disabled={textActionsDisabled}
          onClick={() => setShowFullText((prev) => !prev)}
        >
          <HistoryIcon kind="eye" />
          <span>{showFullText ? 'Hide Full Text' : 'View Full Text'}</span>
        </button>
        <button type="button" className="transcription-history-action" disabled={textActionsDisabled} onClick={handleCopy}>
          <HistoryIcon kind={copied ? 'copied' : 'copy'} />
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>

        <div
          ref={retranscribeMenuRef}
          className="transcription-history-retranscribe-control"
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) setShowRetranscribeMenu(false)
          }}
        >
          <button
            type="button"
            className={`transcription-history-action transcription-history-retry-action${isFailed ? ' transcription-history-retry-action-failed' : ''}`}
            disabled={actionPending || isRetranscribing || isPending}
            aria-expanded={availableRetranscriptionModels.length > 0 ? showRetranscribeMenu : undefined}
            aria-haspopup={availableRetranscriptionModels.length > 0 ? 'menu' : undefined}
            aria-label={isRetranscribing ? 'Retranscribing' : isFailed ? 'Retry transcription' : 'Retranscribe'}
            title={isRetranscribing ? 'Retranscribing' : isFailed ? 'Retry transcription' : 'Retranscribe'}
            onClick={() => {
              if (availableRetranscriptionModels.length === 0) {
                handleRetranscribeClick()
              } else {
                setShowRetranscribeMenu((current) => !current)
              }
            }}
          >
            <HistoryIcon kind="retry" />
            {isFailed && <span>Retry</span>}
            {availableRetranscriptionModels.length > 0 && <HistoryIcon kind="chevron" />}
          </button>
          {showRetranscribeMenu && (
            <div className="transcription-history-retranscribe-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => handleRetranscribeClick()}>
                Retranscribe with current model{currentModel ? ` (${currentModel.displayName})` : ''}
              </button>
              {localModels.length > 0 && (
                <div role="group" aria-label="Local Models">
                  <span>Local Models</span>
                  {localModels.map((model) => (
                    <button key={model.id} type="button" role="menuitem" onClick={() => handleRetranscribeClick(model.id)}>{model.displayName}</button>
                  ))}
                </div>
              )}
              {apiModels.length > 0 && (
                <div role="group" aria-label="API Models">
                  <span>API Models</span>
                  {apiModels.map((model) => (
                    <button key={model.id} type="button" role="menuitem" onClick={() => handleRetranscribeClick(model.id)}>{model.displayName}</button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <button
          type="button"
          className="transcription-history-delete-button"
          disabled={actionPending}
          onClick={handleDeleteClick}
          onBlur={() => setConfirmingDelete(false)}
        >
          {confirmingDelete ? <span>Confirm Delete?</span> : <><HistoryIcon kind="delete" /><span className="transcription-history-visually-hidden">Delete</span></>}
        </button>

        <span className="transcription-history-item-model">{record.modelName}</span>
      </div>
    </div>
  )
}
