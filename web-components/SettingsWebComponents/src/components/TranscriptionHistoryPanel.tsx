import { useEffect, useRef, useState } from 'react'
import {
  notifyTranscriptionHistoryReady,
  onTranscriptionHistoryEvent,
  requestDeleteTranscription,
  requestPlayAudio,
  requestRetranscribe,
  requestSetSearchText,
  requestSetTimeFrame,
  requestStopAudio,
} from '../services/transcriptionHistoryBridge'
import { TranscriptionHistoryItem } from './TranscriptionHistoryItem'
import type { TranscriptionHistoryFields, TranscriptionHistoryTimeFrameOption } from '../types'

type HistoryPanelIconKind = 'clear' | 'search' | 'waveform'
const SEARCH_IDLE_DELAY_MS = 500

function HistoryPanelIcon({ kind }: { kind: HistoryPanelIconKind }) {
  if (kind === 'search') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 4.5 4.5" /></svg>
  if (kind === 'clear') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m9 9 6 6m0-6-6 6" /></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13v-2M7.5 17V7M11 20V4M14.5 17V7M18 13v-2M21 16V8" /></svg>
}

export function TranscriptionHistoryPanel() {
  const [fields, setFields] = useState<TranscriptionHistoryFields | null>(null)
  const [timeFrameOptions, setTimeFrameOptions] = useState<TranscriptionHistoryTimeFrameOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const [pendingRowAction, setPendingRowAction] = useState<{ requestId: string; transcriptionId: string } | null>(null)
  const [searchText, setSearchText] = useState('')
  const pendingRowActionRef = useRef<{ requestId: string; transcriptionId: string } | null>(null)
  pendingRowActionRef.current = pendingRowAction

  useEffect(() => {
    const unsubscribe = onTranscriptionHistoryEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setFields(event)
        setLoadError(null)
        if (event.type === 'init') {
          setSearchText(event.searchText)
          setTimeFrameOptions(event.timeFrameOptions)
        }
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') {
        if (event.requestId === pendingRowActionRef.current?.requestId) {
          pendingRowActionRef.current = null
          setPendingRowAction(null)
        }
        setLastError(event.status === 'error' ? event.message ?? 'The action failed.' : null)
      }
    })
    notifyTranscriptionHistoryReady()
    return unsubscribe
  }, [])

  const nativeSearchText = fields?.searchText
  useEffect(() => {
    if (nativeSearchText === undefined || searchText === nativeSearchText) return
    const timeoutId = window.setTimeout(() => requestSetSearchText(searchText), SEARCH_IDLE_DELAY_MS)
    return () => window.clearTimeout(timeoutId)
  }, [nativeSearchText, searchText])

  if (loadError) {
    return <div className="transcription-history-error">{loadError}</div>
  }

  if (!fields) {
    return <div className="transcription-history-loading">Loading transcription history…</div>
  }

  function beginRowAction(transcriptionId: string, request: () => string) {
    if (pendingRowActionRef.current) return
    setLastError(null)
    const requestId = request()
    pendingRowActionRef.current = { requestId, transcriptionId }
    setPendingRowAction({ requestId, transcriptionId })
  }

  return (
    <div className="transcription-history-panel">
      <div className="transcription-history-time-frame" role="tablist">
        {timeFrameOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={fields.timeFrameId === option.id}
            className={`transcription-history-time-frame-tab${fields.timeFrameId === option.id ? ' transcription-history-time-frame-tab-active' : ''}`}
            onClick={() => requestSetTimeFrame(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="transcription-history-search-field">
        <HistoryPanelIcon kind="search" />
        <input
          type="search"
          className="transcription-history-search"
          placeholder="Search transcriptions…"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
        />
        {searchText && (
          <button
            type="button"
            className="transcription-history-search-clear"
            aria-label="Clear transcription search"
            title="Clear search"
            onClick={() => setSearchText('')}
          >
            <HistoryPanelIcon kind="clear" />
          </button>
        )}
      </div>

      {fields.isLoading && fields.transcriptions.length === 0 ? (
        <div className="transcription-history-loading">Loading…</div>
      ) : fields.transcriptions.length === 0 ? (
        <div className="transcription-history-empty">
          <HistoryPanelIcon kind="waveform" />
          <div>
            <p className="transcription-history-empty-title">No transcriptions found</p>
            <p className="transcription-settings-hint">Transcriptions will appear here after you use the voice transcription feature.</p>
          </div>
        </div>
      ) : (
        <div className="transcription-history-list basil-refresh-region" aria-busy={fields.isLoading ? true : undefined}>
          {fields.transcriptions.map((record) => (
            <TranscriptionHistoryItem
              key={record.id}
              record={record}
              isPlaying={fields.currentlyPlayingId === record.id}
              isRetranscribing={fields.activeRetranscriptionId === record.id}
              actionPending={pendingRowAction?.transcriptionId === record.id}
              progressMessage={fields.activeRetranscriptionId === record.id ? fields.retranscriptionProgressMessage : null}
              progressFraction={fields.activeRetranscriptionId === record.id ? fields.retranscriptionProgressFraction : null}
              availableRetranscriptionModels={fields.availableRetranscriptionModels}
              currentGlobalTranscriptionModelId={fields.currentGlobalTranscriptionModelId}
              onPlay={() => beginRowAction(record.id, () => requestPlayAudio(record.id))}
              onStop={() => beginRowAction(record.id, requestStopAudio)}
              onRetranscribe={(modelId) => beginRowAction(record.id, () => requestRetranscribe(record.id, modelId))}
              onDelete={() => beginRowAction(record.id, () => requestDeleteTranscription(record.id))}
            />
          ))}
        </div>
      )}

      {pendingRowAction && <p className="transcription-history-loading" role="status">Updating transcription…</p>}
      {fields.error && <div className="transcription-history-error">{fields.error}</div>}
      {lastError && <div className="transcription-history-error">{lastError}</div>}
    </div>
  )
}
